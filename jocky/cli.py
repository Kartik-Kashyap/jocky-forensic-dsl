"""JOCKY command-line interface.

    jocky run <script.jky>        execute an investigation
    jocky compile <script.jky>    lex + parse, optionally dump tokens/AST
    jocky lint <script.jky>       static checks, no evidence access
    jocky env                     runtime + platform report
    jocky serve                   console UI at http://127.0.0.1:8787
"""

import argparse
import json
import os
import platform
import sys

from . import __version__, LANG, builtins as jb
from .lexer import JockySyntaxError
from .runtime import compile_source, run_source, count_nodes

# ---------------------------------------------------------------------------
# terminal styling
# ---------------------------------------------------------------------------

def _enable_ansi():
    if os.name == "nt":
        try:
            import ctypes
            kernel32 = ctypes.windll.kernel32
            kernel32.SetConsoleMode(kernel32.GetStdHandle(-11), 7)
        except Exception:
            pass


def _enable_utf8():
    """Windows consoles default to a legacy codepage; the report uses
    box-drawing and severity glyphs, so force UTF-8 on our own streams."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError, OSError):
            pass


_TTY = sys.stdout.isatty()

def _c(text, code):
    return f"\033[{code}m{text}\033[0m" if _TTY else text

def bold(t):   return _c(t, "1")
def dim(t):    return _c(t, "2")
def cyan(t):   return _c(t, "36")
def green(t):  return _c(t, "32")
def yellow(t): return _c(t, "33")
def red(t):    return _c(t, "31")
def magenta(t): return _c(t, "35")

SEV_COLOR = {"critical": red, "high": red, "medium": yellow, "low": cyan}


def banner():
    print()
    print(f"  {bold('JOCKY')} {dim('v' + __version__)}  "
          f"{dim('— forensic scripting language')}")
    print(f"  {dim('cross-platform forensic analysis runtime')}")
    print()


# ---------------------------------------------------------------------------
# rendering
# ---------------------------------------------------------------------------

def _clip(value, width):
    text = "" if value is None else str(value)
    if len(text) > width:
        return text[: width - 1] + "…"
    return text


def _plural(n, singular, plural=None):
    return f"{n} {singular if n == 1 else (plural or singular + 's')}"


def render_table(table, max_rows=12):
    cols = table["columns"][:6]
    if not cols:
        print(dim("    (no columns)"))
        return
    widths = {}
    for c in cols:
        widest = len(c)
        for row in table["rows"][:max_rows]:
            widest = max(widest, len(_clip(row.get(c), 34)))
        widths[c] = min(widest, 34)

    head = "  ".join(bold(_clip(c, widths[c]).ljust(widths[c])) for c in cols)
    print("    " + head)
    print("    " + dim("  ".join("─" * widths[c] for c in cols)))

    for row in table["rows"][:max_rows]:
        cells = [dim(_clip(row.get(c), widths[c]).ljust(widths[c])) for c in cols]
        # highlight threat-intel matches without shouting
        print("    " + "  ".join(cells))

    shown = min(len(table["rows"]), max_rows)
    if table["total"] > shown:
        print(dim(f"    … {_plural(table['total'] - shown, 'more row')}"))


def render_artifacts(art):
    stats = art["stats"]

    if art.get("report"):
        print(f"  {bold(art['report'])}")
    if art.get("case"):
        print(f"  {dim('case')} {cyan(art['case'])}")
    print()

    for line in art["log"]:
        tag, _, rest = line.partition("]")
        tag = tag.lstrip("[")
        colour = {
            "case": magenta, "ingest": cyan, "let": green,
            "match": yellow, "timeline": cyan, "report": magenta,
            "finding/critical": red, "finding/high": red,
            "finding/medium": yellow, "finding/low": cyan,
            "print": green,
        }.get(tag, dim)
        print(f"  {colour('▸')} {dim(tag.ljust(8))} {rest.strip()}")

    if art["errors"]:
        print()
        for err in art["errors"]:
            print(f"  {red('✗')} {err}")

    for table in art["tables"]:
        print()
        label = table.get("label") or table["name"]
        print(f"  {bold(label)}  {dim(_plural(table['total'], 'record'))}")
        render_table(table)

    if art["findings"]:
        print()
        print(f"  {bold('FINDINGS')}")
        for f in art["findings"]:
            paint = SEV_COLOR.get(f["severity"], dim)
            sev = f["severity"].upper().ljust(8)
            cite = f"({_plural(f['rows'], 'record')} via {f['source']})"
            print(f"    {paint('●')} {paint(sev)} {f['title']}  {dim(cite)}")

    if art.get("timeline"):
        tl = art["timeline"]
        detail = f"({_plural(tl['count'], 'event')} on {tl['field']})"
        print()
        print(f"  {bold('TIMELINE')} {dim(tl['label'])} {dim(detail)}")
        for ev in tl["events"][:10]:
            host = _clip(ev["host"] or "-", 13).ljust(13)
            print(f"    {dim(ev['timestamp'])}  {cyan(host)} "
                  f"{_clip(ev['summary'], 58)}")
        if tl["count"] > 10:
            print(dim(f"    … {_plural(tl['count'] - 10, 'more event')}"))

    print()
    print("  " + dim(
        f"{stats['tokens']} tokens · {stats['nodes']} AST nodes · "
        f"{stats['sources']} sources · {stats['records_read']} records read · "
        f"{stats['duration_ms']} ms"))


# ---------------------------------------------------------------------------
# commands
# ---------------------------------------------------------------------------

def _read(path):
    if not os.path.exists(path):
        print(red(f"error: no such script: {path}"))
        sys.exit(2)
    with open(path, "r", encoding="utf-8") as fh:
        return fh.read()


def _syntax_error(exc, filename):
    print()
    print(f"  {red('✗ syntax error')} {dim(filename)}:{exc.line}:{exc.col}")
    print(f"    {exc.message}")
    if exc.source_line:
        gutter = str(exc.line).rjust(4)
        print()
        print(f"    {dim(gutter + ' │')} {exc.source_line}")
        print(f"    {dim('     │')} {' ' * max(0, exc.col - 1)}{red('^')}")
    print()


def cmd_run(args):
    src = _read(args.script)
    try:
        art, _tokens = run_source(src, filename=args.script,
                                  case=args.case, collect_tokens=True)
    except JockySyntaxError as exc:
        _syntax_error(exc, args.script)
        sys.exit(1)

    if args.json:
        print(json.dumps(art, indent=2, default=str))
    else:
        banner()
        render_artifacts(art)

    if art.get("errors"):
        sys.exit(1)


def cmd_compile(args):
    src = _read(args.script)
    try:
        ast, tokens = compile_source(src, args.script)
    except JockySyntaxError as exc:
        _syntax_error(exc, args.script)
        sys.exit(1)

    if args.json:
        print(json.dumps({
            "tokens": [t.to_dict() for t in tokens],
            "ast": ast,
            "stats": {"tokens": len(tokens) - 1, "nodes": count_nodes(ast)},
        }, indent=2, default=str))
        return

    banner()
    if args.tokens:
        print(f"  {bold('TOKENS')} {dim(f'({len(tokens) - 1})')}")
        for t in tokens:
            if t.kind == "eof":
                continue
            print(f"    {dim(f'{t.line}:{str(t.col).ljust(3)}')} "
                  f"{cyan(t.kind.ljust(6))} {t.value!r}")
        print()

    print(f"  {bold('AST')}")
    print(_tree(ast))
    print()
    print("  " + green("✓ parse ok") + dim(
        f"  {len(tokens) - 1} tokens · {count_nodes(ast)} nodes"))
    print()


def _tree(node, prefix="    ", label=None):
    lines = []
    if isinstance(node, dict):
        head = node.get("node", "?")
        extras = {k: v for k, v in node.items()
                  if k not in ("node", "body", "stages", "args", "items")
                  and not k.startswith("_")
                  and not isinstance(v, (dict, list))}
        suffix = "  " + dim(", ".join(f"{k}={v!r}" for k, v in extras.items())) if extras else ""
        lines.append(f"{prefix}{bold(head)}{suffix}")
        child_prefix = prefix + "  "
        for key in ("body", "source", "left", "right", "cond", "value", "expr"):
            if key in node and isinstance(node[key], (dict, list)):
                lines.append(f"{child_prefix}{dim(key + ':')}")
                lines.append(_tree(node[key], child_prefix + "  "))
        for key in ("stages", "args", "items"):
            if key in node and isinstance(node[key], list):
                lines.append(f"{child_prefix}{dim(key + ':')}")
                for item in node[key]:
                    lines.append(_tree(item, child_prefix + "  "))
        return "\n".join(lines)
    if isinstance(node, list):
        return "\n".join(_tree(item, prefix) for item in node)
    return f"{prefix}{node!r}"


def cmd_lint(args):
    src = _read(args.script)
    problems = []

    try:
        ast, tokens = compile_source(src, args.script)
    except JockySyntaxError as exc:
        _syntax_error(exc, args.script)
        sys.exit(1)

    # static checks that matter for an investigation script
    declared_sources, bound, emitted, cited = set(), set(), set(), set()
    has_timeline = has_report = False

    for stmt in ast["body"]:
        k = stmt["node"]
        if k == "Source":
            declared_sources.add(stmt["name"])
        elif k == "Let":
            bound.add(stmt["name"])
        elif k == "Emit":
            emitted.add(stmt["name"])
        elif k == "Match":
            bound.add(stmt["name"])      # match ... as NAME creates a binding
        elif k == "Finding":
            cited.add(stmt["source"])
        elif k == "Timeline":
            has_timeline = True
        elif k == "Report":
            has_report = True

    if not declared_sources:
        problems.append(("warn", "no evidence declared — add a `source` line"))
    if not has_report:
        problems.append(("warn", "no `report` title — the case file will be unnamed"))
    if not has_timeline:
        problems.append(("info", "no `timeline` — consider one for the case narrative"))
    if not any(stmt["node"] == "Finding" for stmt in ast["body"]):
        problems.append(("warn", "no `finding` — nothing will be raised for review"))

    for name in sorted(cited - bound - declared_sources):
        problems.append(("error", f"finding cites unknown binding {name!r}"))
    for name in sorted(emitted - bound - declared_sources):
        problems.append(("error", f"emit references unknown binding {name!r}"))

    banner()
    counts = f"{len(ast['body'])} statements · {len(declared_sources)} sources"
    print(f"  {bold(args.script)}  {dim(counts)}")
    print()
    icon = {"error": red("✗"), "warn": yellow("!"), "info": dim("·")}
    for level, msg in problems:
        print(f"    {icon[level]} {msg}")
    if not problems:
        print(f"    {green('✓')} no issues found")
    print()
    sys.exit(1 if any(p[0] == "error" for p in problems) else 0)


def cmd_env(args):
    banner()
    import shutil
    rows = [
        ("language", f"{LANG} {__version__}"),
        ("platform", f"{platform.system()} {platform.release()}"),
        ("architecture", platform.machine()),
        ("python", platform.python_version()),
        ("executable", sys.executable),
        ("builtins", f"{len(jb.REGISTRY)} functions"),
        ("evidence dir", os.path.join(os.getcwd(), "evidence")),
    ]
    for k, v in rows:
        print(f"  {dim(k.ljust(14))} {v}")
    print()
    print(f"  {bold('built-in functions')}")
    for fn in jb.describe():
        print(f"    {cyan(fn['name'].ljust(14))} {dim(fn['arity'].ljust(4))} {fn['doc']}")
    print()


def cmd_serve(args):
    from .serve import serve
    serve(host=args.host, port=args.port, root=args.root)


def cmd_version(args):
    print(f"{LANG} {__version__}")


# ---------------------------------------------------------------------------
# entry point
# ---------------------------------------------------------------------------

def build_parser():
    p = argparse.ArgumentParser(
        prog="jocky",
        description="JOCKY — a forensic scripting language for computer and "
                    "network analysis.",
    )
    p.add_argument("--version", action="version", version=f"{LANG} {__version__}")
    sub = p.add_subparsers(dest="command")

    r = sub.add_parser("run", help="execute an investigation script")
    r.add_argument("script")
    r.add_argument("--json", action="store_true", help="emit artifacts as JSON")
    r.add_argument("--case", help="override the case identifier")
    r.set_defaults(func=cmd_run)

    c = sub.add_parser("compile", help="lex and parse without executing")
    c.add_argument("script")
    c.add_argument("--tokens", action="store_true", help="dump the token stream")
    c.add_argument("--ast", action="store_true", help="dump the AST (default)")
    c.add_argument("--json", action="store_true", help="emit tokens and AST as JSON")
    c.set_defaults(func=cmd_compile)

    l = sub.add_parser("lint", help="static checks on a script")
    l.add_argument("script")
    l.set_defaults(func=cmd_lint)

    e = sub.add_parser("env", help="show runtime and platform details")
    e.set_defaults(func=cmd_env)

    s = sub.add_parser("serve", help="run the JOCKY console UI")
    s.add_argument("--host", default="127.0.0.1")
    s.add_argument("--port", type=int, default=8787)
    s.add_argument("--root", default=os.getcwd())
    s.set_defaults(func=cmd_serve)

    v = sub.add_parser("version", help="print the version")
    v.set_defaults(func=cmd_version)

    return p


def main(argv=None):
    _enable_utf8()
    _enable_ansi()
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "command", None):
        parser.print_help()
        return 0
    args.func(args)
    return 0
