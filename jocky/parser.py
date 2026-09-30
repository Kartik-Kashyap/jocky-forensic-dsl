"""JOCKY parser — token stream to an AST.

The AST is plain nested dicts so it can be handed straight to the console
UI as JSON as well as executed by `runtime.py`.
"""

from .lexer import Lexer, JockySyntaxError

CMP_OPS = {"==", "!=", "<", "<=", ">", ">=", "~"}
CMP_KW = {"contains", "startswith", "endswith", "matches", "in"}
SEVERITIES = {"low", "medium", "high", "critical"}


def _node(node_type, **fields):
    """Build an AST node. `node` holds the type; other keys are payload."""
    fields["node"] = node_type
    return fields


class Parser:
    def __init__(self, tokens, source=None, filename="<script>"):
        self.toks = tokens
        self.i = 0
        self.src = source or ""
        self.filename = filename
        self.lines = self.src.splitlines()

    # -- token helpers ----------------------------------------------------
    @property
    def cur(self):
        return self.toks[self.i]

    def at(self, kind, value=None):
        t = self.cur
        return t.kind == kind and (value is None or t.value == value)

    def accept(self, kind, value=None):
        if self.at(kind, value):
            t = self.cur
            self.i += 1
            return t
        return None

    def expect(self, kind, value=None, what=None):
        t = self.accept(kind, value)
        if t is None:
            got = self.cur
            want = what or (value if value is not None else kind)
            found = "end of file" if got.kind == "eof" else repr(got.value)
            self._error(f"expected {want}, found {found}", got)
        return t

    def _error(self, msg, tok=None):
        tok = tok or self.cur
        src_line = None
        if 1 <= tok.line <= len(self.lines):
            src_line = self.lines[tok.line - 1]
        raise JockySyntaxError(msg, tok.line, tok.col, src_line)

    def _field_name(self):
        """Read a field name.

        Keywords are accepted here so that derived columns such as `count`
        (produced by `group by`) remain addressable in later stages.
        """
        t = self.cur
        if t.kind in ("ident", "kw"):
            self.i += 1
            return t
        self._error(f"expected a field name, found {t.value!r}", t)

    # -- entry point ------------------------------------------------------
    def parse_program(self):
        body = []
        while not self.at("eof"):
            body.append(self.parse_statement())
        return _node("Program", body=body, filename=self.filename)

    # -- statements -------------------------------------------------------
    def parse_statement(self):
        t = self.cur

        if t.kind == "kw":
            handler = {
                "case": self._case_stmt,
                "source": self._source_stmt,
                "let": self._let_stmt,
                "emit": self._emit_stmt,
                "print": self._print_stmt,
                "match": self._match_stmt,
                "timeline": self._timeline_stmt,
                "report": self._report_stmt,
                "finding": self._finding_stmt,
            }.get(t.value)
            if handler:
                return handler()

        self._error(f"unexpected {t.value!r} at start of statement", t)

    def _case_stmt(self):
        line = self.expect("kw", "case")
        name = self.expect("str", what="a case identifier string")
        return _node("Case", name=name.value, line=line.line)

    def _source_stmt(self):
        line = self.expect("kw", "source")
        name = self.expect("ident", what="a source name")
        self.expect("op", "=", what="'='")
        self.expect("kw", "ingest", what="'ingest'")
        path = self.expect("str", what="an evidence file path")
        kind = None
        if self.accept("kw", "as"):
            kind = self.expect("ident", what="a source type").value
        return _node("Source", name=name.value, path=path.value,
                     kind=kind, line=line.line)

    def _let_stmt(self):
        line = self.expect("kw", "let")
        name = self.expect("ident", what="a binding name")
        self.expect("op", "=", what="'='")
        value = self.parse_pipe()
        return _node("Let", name=name.value, value=value, line=line.line)

    def _emit_stmt(self):
        line = self.expect("kw", "emit")
        name = self.expect("ident", what="a binding name to emit")
        label = None
        if self.accept("kw", "as"):
            label = self.expect("str", what="a display label").value
        return _node("Emit", name=name.value, label=label, line=line.line)

    def _print_stmt(self):
        line = self.expect("kw", "print")
        return _node("Print", value=self.parse_cond(), line=line.line)

    def _match_stmt(self):
        line = self.expect("kw", "match")
        table = self.expect("ident", what="a source name")
        self.expect("punct", ".", what="'.'")
        field = self.expect("ident", what="a field name")
        self.expect("kw", "against", what="'against'")
        intel = self.expect("str", what="a threat-intel file path")
        name = f"{table.value}_{field.value}_matches"
        if self.accept("kw", "as"):
            name = self.expect("ident", what="a result name").value
        return _node("Match", table=table.value, field=field.value,
                     against=intel.value, name=name, line=line.line)

    def _timeline_stmt(self):
        line = self.expect("kw", "timeline")
        table = self.expect("ident", what="a source name")
        self.expect("kw", "on", what="'on'")
        field = self.expect("ident", what="a timestamp field")
        label = table.value
        if self.accept("kw", "as"):
            label = self.expect("str", what="a timeline label").value
        return _node("Timeline", table=table.value, on=field.value,
                     label=label, line=line.line)

    def _report_stmt(self):
        line = self.expect("kw", "report")
        title = self.expect("str", what="a report title")
        return _node("Report", title=title.value, line=line.line)

    def _finding_stmt(self):
        line = self.expect("kw", "finding")
        title = self.expect("str", what="a finding title")
        self.expect("kw", "severity", what="'severity'")
        sev = self.expect("ident", what="a severity level")
        if sev.value not in SEVERITIES:
            self._error(
                f"unknown severity {sev.value!r}; expected one of "
                f"{', '.join(sorted(SEVERITIES))}", sev)
        self.expect("kw", "from", what="'from'")
        src = self.expect("ident", what="the binding this finding cites")
        return _node("Finding", title=title.value, severity=sev.value,
                     source=src.value, line=line.line)

    # -- pipeline ---------------------------------------------------------
    def parse_pipe(self):
        base = self.parse_primary()
        stages = []
        while self.at("op", "|>") or self.at("punct", "|"):
            self.i += 1
            stages.append(self.parse_stage())
        if not stages:
            return base
        return _node("Pipe", source=base, stages=stages)

    def parse_primary(self):
        t = self.cur
        if t.kind == "ident":
            self.i += 1
            return _node("Ref", name=t.value, line=t.line)
        if t.kind == "punct" and t.value == "(":
            self.i += 1
            inner = self.parse_pipe()
            self.expect("punct", ")", what="')'")
            return inner
        self._error(f"expected a data source name, found {t.value!r}", t)

    def parse_stage(self):
        t = self.cur
        if t.kind != "kw":
            self._error(f"expected a pipeline stage, found {t.value!r}", t)

        if t.value == "where":
            self.i += 1
            self.expect("punct", "(", what="'(' after 'where'")
            cond = self.parse_cond()
            self.expect("punct", ")", what="')'")
            return _node("Where", cond=cond, line=t.line)

        if t.value == "select":
            self.i += 1
            return _node("Select", fields=self._field_list("select"), line=t.line)

        if t.value == "sort":
            self.i += 1
            self.expect("kw", "by", what="'by' after 'sort'")
            self.expect("punct", "(", what="'(' after 'sort by'")
            field = self._field_name().value
            direction = "asc"
            if self.at("kw", "asc") or self.at("kw", "desc"):
                direction = self.cur.value
                self.i += 1
            self.expect("punct", ")", what="')'")
            return _node("SortBy", field=field, direction=direction, line=t.line)

        if t.value == "limit":
            self.i += 1
            self.expect("punct", "(", what="'(' after 'limit'")
            n = self.expect("num", what="a record count")
            self.expect("punct", ")", what="')'")
            if not isinstance(n.value, int):
                self._error("'limit' takes a whole number", n)
            return _node("Limit", n=n.value, line=t.line)

        if t.value == "count":
            self.i += 1
            return _node("Count", line=t.line)

        if t.value == "group":
            self.i += 1
            self.expect("kw", "by", what="'by' after 'group'")
            return _node("GroupBy", fields=self._field_list("group by"), line=t.line)

        if t.value == "distinct":
            self.i += 1
            return _node("Distinct", **self._one_field("distinct"), line=t.line)

        if t.value == "as":
            self.i += 1
            label = self.expect("str", what="a display label")
            return _node("As", label=label.value, line=t.line)

        self._error(f"unknown pipeline stage {t.value!r}", t)

    def _field_list(self, stage):
        self.expect("punct", "(", what=f"'(' after '{stage}'")
        fields = [self._field_name().value]
        while self.accept("punct", ","):
            fields.append(self._field_name().value)
        self.expect("punct", ")", what="')'")
        return fields

    def _one_field(self, stage):
        self.expect("punct", "(", what=f"'(' after '{stage}'")
        field = self._field_name().value
        self.expect("punct", ")", what="')'")
        return {"field": field}

    # -- conditions -------------------------------------------------------
    def parse_cond(self):
        return self._or_expr()

    def _or_expr(self):
        left = self._and_expr()
        while self.accept("kw", "or"):
            right = self._and_expr()
            left = _node("Logic", op="or", left=left, right=right)
        return left

    def _and_expr(self):
        left = self._cmp()
        while self.accept("kw", "and"):
            right = self._cmp()
            left = _node("Logic", op="and", left=left, right=right)
        return left

    def _cmp(self):
        if self.at("kw", "not"):
            self.i += 1
            return _node("Not", expr=self._cmp())

        left = self._operand()
        t = self.cur
        op = None
        if t.kind == "op" and t.value in CMP_OPS:
            op = t.value
        elif t.kind == "kw" and t.value in CMP_KW:
            op = t.value
        if op is None:
            return left

        self.i += 1
        right = self._operand()
        if op == "in" and right.get("node") != "List":
            self._error("the right side of 'in' must be a [ ... ] list", t)
        return _node("Compare", op=op, left=left, right=right)

    def _operand(self):
        t = self.cur

        if t.kind == "str":
            self.i += 1
            return _node("Literal", type="string", value=t.value)
        if t.kind == "num":
            self.i += 1
            return _node("Literal", type="number", value=t.value)
        if t.kind == "kw" and t.value in ("true", "false"):
            self.i += 1
            return _node("Literal", type="bool", value=(t.value == "true"))
        if t.kind == "kw" and t.value == "null":
            self.i += 1
            return _node("Literal", type="null", value=None)
        if t.kind == "punct" and t.value == "[":
            return self._list_literal()
        if t.kind == "ident":
            self.i += 1
            if self.at("punct", "("):
                args = self._call_args()
                return _node("Call", name=t.value, args=args, line=t.line)
            return _node("Field", name=t.value, line=t.line)
        if t.kind == "punct" and t.value == "(":
            self.i += 1
            inner = self.parse_cond()
            self.expect("punct", ")", what="')'")
            return inner

        self._error(f"expected a value in this condition, found {t.value!r}", t)

    def _call_args(self):
        self.expect("punct", "(", what="'('")
        args = []
        if not self.at("punct", ")"):
            args.append(self._operand())
            while self.accept("punct", ","):
                args.append(self._operand())
        self.expect("punct", ")", what="')'")
        return args

    def _list_literal(self):
        self.expect("punct", "[", what="'['")
        items = []
        if not self.at("punct", "]"):
            items.append(self._operand())
            while self.accept("punct", ","):
                items.append(self._operand())
        self.expect("punct", "]", what="']'")
        return _node("List", items=items)


def parse(source, filename="<script>"):
    """Parse JOCKY source text into an AST."""
    toks = Lexer(source, filename).tokens()
    return Parser(toks, source=source, filename=filename).parse_program()
