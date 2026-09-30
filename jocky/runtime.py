"""JOCKY runtime — executes the AST over evidence.

The runtime is deliberately boring: evidence loads into lists of dicts,
each pipeline stage is a list-to-list transform, and every table it
produces is returned as JSON-safe data for the CLI or the console UI.
"""

import csv
import json
import os
import re
import time

from . import builtins as jb
from .lexer import tokenize, JockySyntaxError
from .parser import parse

MAX_ROWS = 250          # rows handed to the UI per table
PREVIEW_ROWS = 5        # rows shown in the evidence browser


class JockyRuntimeError(Exception):
    def __init__(self, message, line=None):
        self.message = message
        self.line = line
        super().__init__(message if line is None else f"line {line}: {message}")

    def to_dict(self):
        return {"message": self.message, "line": self.line}


# ---------------------------------------------------------------------------
# evidence loading
# ---------------------------------------------------------------------------

def _load_evidence(path):
    """Load a JSON, CSV or line-based evidence file into records."""
    ext = os.path.splitext(path)[1].lower()

    if ext == ".json":
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        if isinstance(data, dict):
            for key in ("records", "events", "data", "items"):
                if isinstance(data.get(key), list):
                    data = data[key]
                    break
            else:
                data = [data]
        if not isinstance(data, list):
            raise JockyRuntimeError(f"{path}: expected a list of records")
        return [r if isinstance(r, dict) else {"value": r} for r in data]

    if ext == ".csv":
        with open(path, "r", encoding="utf-8", newline="") as fh:
            return [dict(row) for row in csv.DictReader(fh)]

    # anything else: one record per non-empty line
    with open(path, "r", encoding="utf-8") as fh:
        return [
            {"value": line.strip()}
            for line in fh
            if line.strip() and not line.lstrip().startswith("#")
        ]


def _load_intel(path):
    """Load an indicator list into a set of lowercased strings."""
    indicators = set()
    with open(path, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line and not line.startswith("#"):
                indicators.add(line.lower())
    return indicators


def _resolve(path, script_dir):
    """Resolve an evidence path relative to the script, then the cwd."""
    if os.path.isabs(path) and os.path.exists(path):
        return path
    candidates = [
        os.path.join(script_dir, path),
        os.path.join(os.getcwd(), path),
        path,
    ]
    for cand in candidates:
        if os.path.exists(cand):
            return os.path.abspath(cand)
    raise JockyRuntimeError(
        f"evidence file not found: {path}\n"
        f"  looked in: {script_dir}, {os.getcwd()}")


# ---------------------------------------------------------------------------
# value helpers
# ---------------------------------------------------------------------------

def _lookup(record, name):
    """Field access, supporting dotted paths."""
    if record is None:
        return None
    if name in record:
        return record[name]
    if "." in name:
        cur = record
        for part in name.split("."):
            if isinstance(cur, dict) and part in cur:
                cur = cur[part]
            else:
                return None
        return cur
    return None


def _text(v):
    return "" if v is None else str(v)


def _numeric(v):
    """Return a float if the value looks numeric, else None."""
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str):
        try:
            return float(v.strip())
        except ValueError:
            return None
    return None


def _equals(a, b):
    if a is None and b is None:
        return True
    if a is None or b is None:
        return False
    if isinstance(a, bool) or isinstance(b, bool):
        return a is b if isinstance(a, bool) and isinstance(b, bool) else \
            _text(a).lower() == _text(b).lower()
    na, nb = _numeric(a), _numeric(b)
    if na is not None and nb is not None:
        return na == nb
    return _text(a) == _text(b)


def _order(a, b):
    na, nb = _numeric(a), _numeric(b)
    if na is not None and nb is not None:
        return (na > nb) - (na < nb)
    sa, sb = _text(a).lower(), _text(b).lower()
    return (sa > sb) - (sa < sb)


def _truthy(v):
    if isinstance(v, bool):
        return v
    if v is None:
        return False
    if isinstance(v, (int, float)):
        return v != 0
    return bool(_text(v))


# ---------------------------------------------------------------------------
# runtime
# ---------------------------------------------------------------------------

class Runtime:
    def __init__(self, filename="<script>", case=None):
        self.filename = filename
        self.script_dir = os.path.dirname(os.path.abspath(filename)) or os.getcwd()
        self.sources = {}          # name -> records
        self.source_meta = {}      # name -> {path, records}
        self.bindings = {}         # name -> records
        self.labels = {}           # name -> display label
        self.case = None
        self.case_override = case  # --case on the CLI wins over the script
        self.report_title = None
        self.timeline = None
        self.findings = []
        self.tables = []
        self.log = []
        self.errors = []
        self.records_read = 0
        self._emitted = set()
        self.intel_cache = {}

    # -- logging ----------------------------------------------------------
    def say(self, msg):
        self.log.append(msg)

    # -- entry point ------------------------------------------------------
    def execute(self, ast):
        for stmt in ast.get("body", []):
            self.exec_statement(stmt)
        return self.artifacts(ast)

    def exec_statement(self, stmt):
        kind = stmt["node"]
        handler = getattr(self, f"_st_{kind.lower()}", None)
        if handler is None:
            raise JockyRuntimeError(f"cannot execute {kind}", stmt.get("line"))
        handler(stmt)

    # -- statements -------------------------------------------------------
    def _st_case(self, stmt):
        self.case = stmt["name"]
        if self.case_override and self.case_override != self.case:
            self.say(f"[case] {stmt['name']} -> overridden to "
                     f"{self.case_override}")
        else:
            self.say(f"[case] {stmt['name']}")

    def _st_source(self, stmt):
        path = _resolve(stmt["path"], self.script_dir)
        records = _load_evidence(path)
        self.sources[stmt["name"]] = records
        self.source_meta[stmt["name"]] = {
            "path": path,
            "given": stmt["path"],
            "records": len(records),
            "columns": self._columns(records),
        }
        self.records_read += len(records)
        self.say(f"[ingest] {stmt['name']} <- {stmt['path']} "
                 f"({len(records)} records)")

    def _st_let(self, stmt):
        records = self.eval_pipe(stmt["value"])
        self.bindings[stmt["name"]] = records
        self.say(f"[let] {stmt['name']}: {len(records)} records")

    def _st_emit(self, stmt):
        name = stmt["name"]
        records = self.bindings.get(name)
        if records is None:
            records = self.sources.get(name)
        if records is None:
            self.errors.append(f"emit: unknown binding {name!r}")
            return
        if name in self._emitted:
            return
        self._emitted.add(name)
        self.tables.append(self._table(name, stmt.get("label") or self.labels.get(name), records))

    def _st_print(self, stmt):
        value = self.eval_cond(stmt["value"], {})
        self.say(f"[print] {value}")

    def _st_match(self, stmt):
        table = stmt["table"]
        if table not in self.sources:
            self.errors.append(f"match: unknown source {table!r}")
            return
        path = _resolve(stmt["against"], self.script_dir)
        if path not in self.intel_cache:
            self.intel_cache[path] = _load_intel(path)
        intel = self.intel_cache[path]

        hits = []
        for rec in self.sources[table]:
            val = _text(_lookup(rec, stmt["field"]))
            if val and val.lower() in intel:
                enriched = dict(rec)
                enriched["_intel_match"] = val
                hits.append(enriched)

        name = stmt["name"]
        self.bindings[name] = hits
        self.labels[name] = f"{stmt['field']} in {os.path.basename(path)}"
        self.say(f"[match] {name}: {len(hits)} of {len(self.sources[table])} "
                 f"records matched {len(intel)} indicators")

    def _st_timeline(self, stmt):
        table = stmt["table"]
        records = self.sources.get(table) or self.bindings.get(table)
        if records is None:
            self.errors.append(f"timeline: unknown table {table!r}")
            return
        field = stmt["on"]
        events = []
        for rec in records:
            ts = _lookup(rec, field)
            if ts is None:
                continue
            events.append({
                "timestamp": _text(ts),
                "epoch": jb.fn_epoch(ts),
                "host": _text(_lookup(rec, "host")),
                "summary": self._summarize(rec),
                "record": {k: v for k, v in rec.items() if not k.startswith("_")},
            })
        events.sort(key=lambda e: (e["epoch"], e["timestamp"]))
        self.timeline = {
            "label": stmt["label"],
            "field": field,
            "count": len(events),
            "events": events[:MAX_ROWS],
        }
        self.say(f"[timeline] {stmt['label']}: {len(events)} events on {field}")

    def _st_report(self, stmt):
        self.report_title = stmt["title"]
        self.say(f"[report] {stmt['title']}")

    def _st_finding(self, stmt):
        src = stmt["source"]
        records = self.bindings.get(src)
        if records is None:
            records = self.sources.get(src)
        if records is None:
            self.errors.append(
                f"finding cites unknown binding {src!r}")
            return
        self.findings.append({
            "title": stmt["title"],
            "severity": stmt["severity"],
            "source": src,
            "label": self.labels.get(src, src),
            "rows": len(records),
        })
        self.say(f"[finding/{stmt['severity']}] {stmt['title']}")

    # -- pipelines --------------------------------------------------------
    def eval_pipe(self, expr):
        if expr["node"] == "Pipe":
            records = self.eval_pipe(expr["source"])
            for stage in expr["stages"]:
                records = self.eval_stage(stage, records)
            return records
        if expr["node"] == "Ref":
            return self._ref(expr["name"], expr.get("line"))
        raise JockyRuntimeError(f"cannot evaluate {expr['node']}")

    def _ref(self, name, line=None):
        if name in self.bindings:
            return self.bindings[name]
        if name in self.sources:
            return self.sources[name]
        known = sorted(set(self.bindings) | set(self.sources))
        raise JockyRuntimeError(
            f"unknown data source {name!r}; available: {', '.join(known) or 'none'}",
            line)

    def eval_stage(self, stage, records):
        kind = stage["node"]

        if kind == "Where":
            return [r for r in records if _truthy(self.eval_cond(stage["cond"], r))]

        if kind == "Select":
            fields = stage["fields"]
            out = []
            for r in records:
                out.append({f: _lookup(r, f) for f in fields})
            return out

        if kind == "SortBy":
            field, direction = stage["field"], stage["direction"]
            present = [r for r in records if _lookup(r, field) is not None]
            missing = [r for r in records if _lookup(r, field) is None]
            present.sort(
                key=lambda r: _SortKey(_lookup(r, field)),
                reverse=(direction == "desc"))
            return present + missing

        if kind == "Limit":
            return records[: stage["n"]]

        if kind == "Count":
            return [{"count": len(records)}]

        if kind == "GroupBy":
            fields = stage["fields"]
            buckets = {}
            for r in records:
                key = tuple(_text(_lookup(r, f)) for f in fields)
                entry = buckets.setdefault(key, {f: key[i] for i, f in enumerate(fields)})
                entry["count"] = entry.get("count", 0) + 1
            return sorted(buckets.values(), key=lambda e: -e["count"])

        if kind == "Distinct":
            field = stage["field"]
            counts = {}
            first_value = {}
            for r in records:
                v = _lookup(r, field)
                key = _text(v)
                counts[key] = counts.get(key, 0) + 1
                first_value.setdefault(key, v)
            out = [{field: first_value[k], "count": counts[k]} for k in counts]
            out.sort(key=lambda e: (-e["count"], _text(e[field]).lower()))
            return out

        if kind == "As":
            # purely a display label; attach to the most recent binding name
            return records

        raise JockeyRuntimeError(f"unknown pipeline stage {kind}",
                                 stage.get("line"))

    # -- expressions ------------------------------------------------------
    def eval_cond(self, expr, record):
        kind = expr["node"]

        if kind == "Logic":
            left = self.eval_cond(expr["left"], record)
            if expr["op"] == "and":
                return _truthy(left) and _truthy(self.eval_cond(expr["right"], record))
            return _truthy(left) or _truthy(self.eval_cond(expr["right"], record))

        if kind == "Not":
            return not _truthy(self.eval_cond(expr["expr"], record))

        if kind == "Compare":
            return self._compare(expr, record)

        return self.eval_operand(expr, record)

    def _compare(self, expr, record):
        op = expr["op"]
        left = self.eval_operand(expr["left"], record)
        right = self.eval_operand(expr["right"], record)

        if op == "==":
            return _equals(left, right)
        if op == "!=":
            return not _equals(left, right)
        if op == "in":
            target = right if isinstance(right, list) else []
            return any(_equals(left, item) for item in target)

        if left is None or right is None:
            return False

        if op in ("<", "<=", ">", ">="):
            c = _order(left, right)
            return {"<": c < 0, "<=": c <= 0, ">": c > 0, ">=": c >= 0}[op]

        ls, rs = _text(left), _text(right)
        if op == "contains":
            return rs.lower() in ls.lower()
        if op == "startswith":
            return ls.lower().startswith(rs.lower())
        if op == "endswith":
            return ls.lower().endswith(rs.lower())
        if op in ("~", "matches"):
            try:
                return re.search(rs, ls) is not None
            except re.error as exc:
                raise JockyRuntimeError(f"invalid regular expression {rs!r}: {exc}",
                                        expr.get("line")) from exc

        raise JockyRuntimeError(f"unknown operator {op!r}", expr.get("line"))

    def eval_operand(self, expr, record):
        kind = expr["node"]

        if kind == "Literal":
            return expr["value"]
        if kind == "Field":
            return _lookup(record, expr["name"])
        if kind == "List":
            return [self.eval_operand(item, record) for item in expr["items"]]
        if kind == "Call":
            return self._call(expr, record)
        if kind in ("Logic", "Not", "Compare"):
            return self.eval_cond(expr, record)

        raise JockyRuntimeError(f"cannot evaluate {kind}", expr.get("line"))

    def _call(self, expr, record):
        name = expr["name"]
        entry = jb.REGISTRY.get(name)
        if entry is None:
            known = ", ".join(sorted(jb.REGISTRY))
            raise JockyRuntimeError(
                f"unknown function {name}(); available: {known}", expr.get("line"))

        fn, lo, hi = entry
        args = [self.eval_operand(a, record) for a in expr["args"]]
        if not (lo <= len(args) <= hi):
            want = f"{lo}" if lo == hi else f"{lo} to {hi}"
            raise JockyRuntimeError(
                f"{name}() takes {want} argument(s), got {len(args)}",
                expr.get("line"))
        try:
            return fn(*args)
        except JockyRuntimeError:
            raise
        except Exception as exc:
            raise JockyRuntimeError(
                f"{name}() failed: {exc}", expr.get("line")) from exc

    # -- output shaping ---------------------------------------------------
    def _columns(self, records):
        cols = []
        for r in records[:50]:
            for k in r:
                if k not in cols and not k.startswith("_"):
                    cols.append(k)
        return cols

    def _summarize(self, rec):
        for key in ("command_line", "image", "name", "dst_ip", "query",
                    "path", "value", "device"):
            v = _lookup(rec, key)
            if v:
                return _text(v)
        for k, v in rec.items():
            if not k.startswith("_") and v is not None:
                return f"{k}={v}"
        return ""

    def _table(self, name, label, records):
        return {
            "name": name,
            "label": label or name,
            "columns": self._columns(records),
            "rows": [
                {k: v for k, v in r.items() if not k.startswith("_")}
                for r in records[:MAX_ROWS]
            ],
            "total": len(records),
            "truncated": len(records) > MAX_ROWS,
        }

    def artifacts(self, ast, duration_ms=0.0):
        severity_rank = {"critical": 0, "high": 1, "medium": 2, "low": 3}
        findings = sorted(self.findings,
                          key=lambda f: severity_rank.get(f["severity"], 9))
        return {
            "case": self.case_override or self.case,
            "report": self.report_title,
            "script": os.path.basename(self.filename),
            "sources": self.source_meta,
            "tables": self.tables,
            "findings": findings,
            "timeline": self.timeline,
            "log": self.log,
            "errors": self.errors,
            "stats": {
                "tokens": ast.get("_tokens", 0),
                "nodes": count_nodes(ast),
                "sources": len(self.source_meta),
                "records_read": self.records_read,
                "bindings": len(self.bindings),
                "findings": len(findings),
                "duration_ms": round(duration_ms, 1),
            },
        }


class _SortKey:
    """Total ordering that tolerates mixed and missing values."""
    __slots__ = ("v", "n", "t")

    def __init__(self, v):
        self.v = v
        self.n = _numeric(v)
        self.t = 0 if self.n is not None else 1

    def __lt__(self, other):
        if self.t != other.t:
            return self.t < other.t
        if self.t == 0:
            return self.n < other.n
        return _text(self.v).lower() < _text(other.v).lower()

    def __eq__(self, other):
        return self.t == other.t and (
            self.n == other.n if self.t == 0
            else _text(self.v).lower() == _text(other.v).lower())


def count_nodes(node):
    if isinstance(node, dict):
        return 1 + sum(count_nodes(v) for k, v in node.items() if k != "node")
    if isinstance(node, list):
        return sum(count_nodes(v) for v in node)
    return 0


# ---------------------------------------------------------------------------
# convenience entry point used by the CLI and the server
# ---------------------------------------------------------------------------

def compile_source(source, filename="<script>"):
    """Lex + parse. Returns (ast, tokens). Raises JockySyntaxError."""
    tokens = tokenize(source, filename)
    ast = parse(source, filename)
    ast["_tokens"] = len(tokens) - 1        # exclude EOF
    return ast, tokens


def run_source(source, filename="<script>", case=None, collect_tokens=False):
    """Compile and execute. Returns (artifacts, tokens)."""
    started = time.perf_counter()
    ast, tokens = compile_source(source, filename)
    rt = Runtime(filename=filename, case=case)

    try:
        artifacts = rt.execute(ast)
    except JockyRuntimeError as exc:
        artifacts = rt.artifacts(ast)
        artifacts["errors"].append(exc.message)
        artifacts["fatal"] = exc.to_dict()
    except JockySyntaxError as exc:
        raise

    artifacts["stats"]["duration_ms"] = round(
        (time.perf_counter() - started) * 1000, 1)
    pass  # case precedence is resolved in Runtime.artifacts
    return (artifacts, tokens) if collect_tokens else artifacts
