"""JOCKY lexer — source text to a token stream.

The token stream is exposed to the console UI, so every token carries its
source line and column.
"""

KEYWORDS = {
    # declarations
    "let", "case", "source", "ingest", "as", "emit", "print",
    # pipeline stages
    "where", "select", "sort", "by", "asc", "desc", "limit", "count",
    "group", "distinct", "timeline", "on",
    # threat intel
    "match", "against",
    # reporting
    "report", "finding", "severity", "from",
    # condition operators
    "and", "or", "not", "in", "contains", "startswith", "endswith", "matches",
    # literals
    "true", "false", "null",
}

# Longest-first so that '|>' wins over '|', '<=' over '<', '==' over '='.
OPERATORS = [
    "|>", "==", "!=", "<=", ">=", "~",
    "=", "<", ">", "+", "-", "*", "/", "%",
    "(", ")", "{", "}", "[", "]", ",", ".", ":", "|",
]

ESCAPES = {'"': '"', "'": "'", "\\": "\\"}
# Deliberately minimal. JOCKY source is full of Windows paths and regular
# expressions, so \n, \t, \d and friends must reach the runtime intact
# rather than being consumed by the lexer: "C:\Users\a\Temp" and
# "(?i)appdata\.local" mean exactly what they say. Use forward slashes in
# evidence paths; use \\ only when you need a literal backslash before a
# quote.

# Punctuation-ish operators are reported as 'punct' for readability in the UI.
PUNCT = set("(){}[],.:|")


class JockySyntaxError(Exception):
    """Raised for any lexical or grammatical problem, with source position."""

    def __init__(self, message, line=1, col=1, source_line=None):
        self.message = message
        self.line = line
        self.col = col
        self.source_line = source_line
        detail = f"line {line}, col {col}: {message}"
        super().__init__(detail)

    def to_dict(self):
        return {
            "message": self.message,
            "line": self.line,
            "col": self.col,
            "source_line": self.source_line,
        }


class Token:
    __slots__ = ("kind", "value", "line", "col")

    def __init__(self, kind, value, line, col):
        self.kind = kind      # kw | ident | str | num | op | punct | eof
        self.value = value
        self.line = line
        self.col = col

    def __repr__(self):
        return f"Token({self.kind}, {self.value!r}, {self.line}:{self.col})"

    def to_dict(self):
        return {
            "kind": self.kind,
            "value": self.value,
            "line": self.line,
            "col": self.col,
        }


def _is_ident_start(ch):
    return ch.isalpha() or ch == "_"


def _is_ident_part(ch):
    return ch.isalnum() or ch == "_"


class Lexer:
    def __init__(self, source, filename="<script>"):
        self.src = source
        self.filename = filename
        self.pos = 0
        self.line = 1
        self.col = 1
        self._lines = source.splitlines()

    # -- position helpers -------------------------------------------------
    def _peek(self, offset=0):
        i = self.pos + offset
        return self.src[i] if i < len(self.src) else ""

    def _advance(self):
        ch = self.src[self.pos]
        self.pos += 1
        if ch == "\n":
            self.line += 1
            self.col = 1
        else:
            self.col += 1
        return ch

    def _source_line(self, line):
        if 1 <= line <= len(self._lines):
            return self._lines[line - 1]
        return None

    def _error(self, msg, line=None, col=None):
        line = self.line if line is None else line
        col = self.col if col is None else col
        raise JockySyntaxError(msg, line, col, self._source_line(line))

    # -- main loop --------------------------------------------------------
    def tokens(self):
        out = []
        while self.pos < len(self.src):
            ch = self._peek()

            if ch in " \t\r\n":
                self._advance()
                continue

            if ch == "#":                      # comment to end of line
                while self.pos < len(self.src) and self._peek() != "\n":
                    self._advance()
                continue

            if ch in "\"'":
                out.append(self._string())
                continue

            if ch.isdigit():
                out.append(self._number())
                continue

            if _is_ident_start(ch):
                out.append(self._ident())
                continue

            out.append(self._operator())

        out.append(Token("eof", None, self.line, self.col))
        return out

    # -- scanners ---------------------------------------------------------
    def _string(self):
        quote = self._advance()
        line, col = self.line, self.col - 1
        buf = []
        while True:
            if self.pos >= len(self.src):
                self._error("unterminated string literal", line, col)
            ch = self._advance()
            if ch == "\\":
                if self.pos >= len(self.src):
                    self._error("unterminated escape sequence")
                esc = self._advance()
                if esc in ESCAPES:
                    buf.append(ESCAPES[esc])
                else:
                    # Unrecognised escapes are kept verbatim, backslash and
                    # all, so paths and regexes survive untouched.
                    buf.append("\\")
                    buf.append(esc)
                continue
            if ch == quote:
                break
            if ch == "\n":
                self._error("unterminated string literal", line, col)
            buf.append(ch)
        return Token("str", "".join(buf), line, col)

    def _number(self):
        line, col = self.line, self.col
        buf = []
        if self._peek() == "0" and self._peek(1) in "xX":
            buf.append(self._advance())
            buf.append(self._advance())
            while self._peek() and self._peek() in "0123456789abcdefABCDEF_":
                buf.append(self._advance())
            text = "".join(buf).replace("_", "")
            return Token("num", int(text, 16), line, col)

        seen_dot = False
        while True:
            ch = self._peek()
            if ch.isdigit() or ch == "_":
                buf.append(self._advance())
            elif ch == "." and not seen_dot and self._peek(1).isdigit():
                seen_dot = True
                buf.append(self._advance())
            else:
                break

        text = "".join(buf).replace("_", "")
        value = float(text) if seen_dot else int(text)
        return Token("num", value, line, col)

    def _ident(self):
        line, col = self.line, self.col
        buf = []
        while self._peek() and _is_ident_part(self._peek()):
            buf.append(self._advance())
        word = "".join(buf)
        kind = "kw" if word in KEYWORDS else "ident"
        return Token(kind, word, line, col)

    def _operator(self):
        line, col = self.line, self.col
        for op in OPERATORS:
            if self.src.startswith(op, self.pos):
                for _ in op:
                    self._advance()
                kind = "punct" if op in PUNCT else "op"
                return Token(kind, op, line, col)
        self._error(f"unexpected character {self._peek()!r}")


def tokenize(source, filename="<script>"):
    """Convenience wrapper: source text -> list[Token]."""
    return Lexer(source, filename).tokens()
