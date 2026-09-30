"""JOCKY console server.

Serves the operator UI and an API that runs real JOCKY scripts. The API is
bound to loopback by default: an investigation console that accepts remote
connections by default is a liability, so exposing it is a deliberate act.

    python -m jocky serve --port 8787
"""

import hashlib
import json
import os
import platform
import sys
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

from . import __version__, LANG, builtins as jb
from .lexer import JockySyntaxError
from .runtime import (compile_source, run_source, count_nodes,
                      _load_evidence, JockyRuntimeError, PREVIEW_ROWS)

CONSOLE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           os.pardir, "console")
CONSOLE_FILE = os.path.abspath(os.path.join(CONSOLE_DIR, "index.html"))

# What this project does and does not do. Surfaced verbatim in the console
# so the operating constraints travel with the tool.
DESIGN_CONSTRAINTS = [
    {
        "title": "Documented telemetry sources only",
        "body": "Collectors read ETW, WMI, the USN journal, auditd/eBPF and "
                "netflow. JOCKY does not patch kernel structures, disable "
                "security callbacks, or interfere with endpoint protection.",
    },
    {
        "title": "Signed, reproducible builds",
        "body": "Release artefacts are built from a pinned toolchain and "
                "signed. Hashes are published so security vendors can "
                "allowlist them — obfuscation to defeat detection is "
                "explicitly out of scope.",
    },
    {
        "title": "Local by default",
        "body": "The console listens on 127.0.0.1. Fleet deployment is "
                "opt-in, over TLS with pinned certificates, and requires an "
                "operator to enable it.",
    },
    {
        "title": "Auditable execution",
        "body": "Every script run is logged with its source hash, the "
                "evidence digests it read, and the operator who ran it. "
                "Findings cite the query that produced them.",
    },
    {
        "title": "Read-only collection",
        "body": "Evidence files are opened read-only. Nothing is written "
                "back to a source system, and no remediation is performed "
                "automatically.",
    },
]


def _sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _sha256_text(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class ConsoleState:
    """Reads the project tree: scripts, evidence, fleet."""

    def __init__(self, root):
        self.root = os.path.abspath(root)

    def scripts_dir(self):
        return os.path.join(self.root, "scripts")

    def evidence_dir(self):
        return os.path.join(self.root, "evidence")

    def scripts(self):
        out = []
        d = self.scripts_dir()
        if not os.path.isdir(d):
            return out
        for name in sorted(os.listdir(d)):
            if not name.endswith(".jky"):
                continue
            path = os.path.join(d, name)
            with open(path, "r", encoding="utf-8") as fh:
                src = fh.read()
            out.append({
                "name": name,
                "path": os.path.relpath(path, self.root).replace("\\", "/"),
                "source": src,
                "lines": len(src.splitlines()),
                "sha256": _sha256_text(src),
            })
        return out

    def evidence(self):
        out = []
        d = self.evidence_dir()
        if not os.path.isdir(d):
            return out
        for name in sorted(os.listdir(d)):
            path = os.path.join(d, name)
            if not os.path.isfile(path):
                continue
            rel = os.path.relpath(path, self.root).replace("\\", "/")
            entry = {
                "name": name,
                "path": rel,
                "bytes": os.path.getsize(path),
                "sha256": _sha256_file(path),
                "kind": os.path.splitext(name)[1].lstrip(".").lower(),
            }
            try:
                rows = _load_evidence(path)
                entry["records"] = len(rows)
                cols = []
                for r in rows[:25]:
                    for k in r:
                        if k not in cols:
                            cols.append(k)
                entry["columns"] = cols[:10]
                entry["preview"] = rows[:PREVIEW_ROWS]
            except Exception as exc:                      # noqa: BLE001
                entry["records"] = 0
                entry["columns"] = []
                entry["preview"] = []
                entry["note"] = str(exc)
            out.append(entry)
        return out

    def fleet(self):
        path = os.path.join(self.evidence_dir(), "fleet.json")
        if not os.path.exists(path):
            return []
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)

    def resolve_script(self, rel_path):
        """Map a client-supplied script path into the scripts directory.

        Guards against traversal: the resolved path must stay inside
        scripts/.
        """
        base = self.scripts_dir()
        candidate = os.path.abspath(os.path.join(self.root, rel_path))
        if not candidate.startswith(os.path.abspath(base) + os.sep):
            raise ValueError("script path escapes the scripts directory")
        if not os.path.isfile(candidate):
            raise ValueError(f"no such script: {rel_path}")
        return candidate

    def state(self):
        return {
            "lang": LANG,
            "version": __version__,
            "platform": {
                "system": platform.system(),
                "release": platform.release(),
                "machine": platform.machine(),
                "python": platform.python_version(),
                "executable": sys.executable,
                "cwd": self.root,
            },
            "scripts": self.scripts(),
            "evidence": self.evidence(),
            "fleet": self.fleet(),
            "builtins": jb.describe(),
            "constraints": DESIGN_CONSTRAINTS,
            "grammar": GRAMMAR,
        }


GRAMMAR = [
    {"form": 'case "ID"', "doc": "Name the investigation."},
    {"form": 'source N = ingest "path"', "doc": "Declare an evidence file (JSON, CSV or line-based)."},
    {"form": "let N = src |> where (cond) |> ...", "doc": "Derive a result set from a source."},
    {"form": "let N = src |> select (f1, f2)", "doc": "Project fields."},
    {"form": "let N = src |> sort by (f desc)", "doc": "Order records."},
    {"form": "let N = src |> group by (f)", "doc": "Bucket and count."},
    {"form": "let N = src |> distinct (f)", "doc": "Unique values with counts."},
    {"form": "let N = src |> limit (n)", "doc": "Truncate a result set."},
    {"form": 'match src.field against "intel.txt" as N', "doc": "Correlate against a threat-intel list."},
    {"form": 'timeline src on timestamp as "label"', "doc": "Build the case narrative."},
    {"form": 'report "Title"', "doc": "Name the report."},
    {"form": 'finding "text" severity high from N', "doc": "Raise a finding citing a result set."},
    {"form": 'emit N as "Label"', "doc": "Include a result set in the report."},
]


class Handler(BaseHTTPRequestHandler):
    server_version = f"JOCKY/{__version__}"
    state = None            # set by serve()

    # -- plumbing ---------------------------------------------------------
    def log_message(self, fmt, *args):
        if self.server.verbose:
            sys.stderr.write("  %s\n" % (fmt % args))

    def _send(self, code, body, content_type="application/json"):
        if isinstance(body, (dict, list)):
            body = json.dumps(body, default=str).encode("utf-8")
        elif isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        # The console is a local tool; keep it from being framed or sniffed.
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self):
        length = int(self.headers.get("Content-Length") or 0)
        if not length:
            return {}
        raw = self.rfile.read(length)
        try:
            return json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            raise ValueError("request body is not valid JSON")

    def _local_only(self):
        """Reject anything that did not originate from this machine."""
        host = (self.client_address[0] or "").split("%")[0]
        return host in ("127.0.0.1", "::1", "localhost")

    # -- routes -----------------------------------------------------------
    def do_GET(self):
        path = urlparse(self.path).path

        if not self._local_only():
            return self._send(403, {"error": "console is bound to loopback"})

        if path in ("/", "/index.html"):
            try:
                with open(CONSOLE_FILE, "r", encoding="utf-8") as fh:
                    return self._send(200, fh.read(), "text/html; charset=utf-8")
            except OSError as exc:
                return self._send(500, {"error": f"console not found: {exc}"})

        if path == "/api/state":
            return self._send(200, self.state.state())

        if path == "/api/health":
            return self._send(200, {"ok": True, "version": __version__})

        return self._send(404, {"error": f"no route for {path}"})

    def do_POST(self):
        path = urlparse(self.path).path

        if not self._local_only():
            return self._send(403, {"error": "console is bound to loopback"})

        if path == "/api/run":
            return self._run()

        if path == "/api/compile":
            return self._compile()

        return self._send(404, {"error": f"no route for {path}"})

    def _payload_source(self, body):
        """Either run an inline source buffer or a script on disk."""
        source = body.get("source")
        rel = body.get("path")
        if source is not None:
            label = rel or "<editor>"
            return source, label
        if rel:
            return None, self.state.resolve_script(rel)
        raise ValueError("provide either 'source' or 'path'")

    def _compile(self):
        try:
            body = self._read_json()
            source, label = self._payload_source(body)
            if source is None:
                with open(label, "r", encoding="utf-8") as fh:
                    source = fh.read()
            ast, tokens = compile_source(source, label)
            return self._send(200, {
                "ok": True,
                "tokens": [t.to_dict() for t in tokens],
                "ast": ast,
                "stats": {"tokens": len(tokens) - 1, "nodes": count_nodes(ast)},
            })
        except JockySyntaxError as exc:
            return self._send(200, {"ok": False, "error": exc.to_dict()})
        except (ValueError, OSError) as exc:
            return self._send(400, {"ok": False, "error": {"message": str(exc)}})

    def _run(self):
        try:
            body = self._read_json()
            source, label = self._payload_source(body)
            if source is None:
                with open(label, "r", encoding="utf-8") as fh:
                    source = fh.read()

            ast, tokens = compile_source(source, label)
            artifacts, _ = run_source(source, filename=label,
                                      case=body.get("case"),
                                      collect_tokens=True)

            # The script's evidence paths are relative to the project root.
            return self._send(200, {
                "ok": True,
                "artifacts": artifacts,
                "tokens": [t.to_dict() for t in tokens],
                "ast": ast,
                "source_sha256": _sha256_text(source),
                "stats": {"tokens": len(tokens) - 1, "nodes": count_nodes(ast)},
            })
        except JockySyntaxError as exc:
            return self._send(200, {"ok": False, "error": exc.to_dict()})
        except JockyRuntimeError as exc:
            return self._send(200, {"ok": False, "error": exc.to_dict()})
        except (ValueError, OSError) as exc:
            return self._send(400, {"ok": False, "error": {"message": str(exc)}})
        except Exception as exc:                              # noqa: BLE001
            traceback.print_exc()
            return self._send(500, {"ok": False,
                                    "error": {"message": f"internal error: {exc}"}})


class Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True
    verbose = False


def serve(host="127.0.0.1", port=8787, root=None, verbose=False):
    root = os.path.abspath(root or os.getcwd())
    Handler.state = ConsoleState(root)

    try:
        httpd = Server((host, port), Handler)
    except OSError as exc:
        print(f"\n  could not bind {host}:{port} — {exc}")
        print(f"  try a different port:  python -m jocky serve --port {port + 1}\n")
        return 1

    httpd.verbose = verbose

    print()
    print(f"  JOCKY console  v{__version__}")
    print(f"  root           {root}")
    print(f"  listening      http://{host}:{port}")
    print(f"  scripts        {len(Handler.state.scripts())} found")
    print(f"  evidence       {len(Handler.state.evidence())} files")
    print()
    print("  local only — loopback binding, no remote connections accepted")
    print("  press Ctrl+C to stop")
    print()

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n  console stopped\n")
    finally:
        httpd.server_close()
    return 0
