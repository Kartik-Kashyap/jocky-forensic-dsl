"""JOCKY — a small domain-specific language for computer & network forensics.

JOCKY scripts describe an investigation as a pipeline over evidence:
declare sources, transform them, match them against threat intel, and
raise findings. Everything here is real: the lexer, the parser, and the
runtime that executes the AST in `runtime.py`.
"""

__version__ = "0.1.0"
LANG = "JOCKY"

from .lexer import Lexer, Token, JockySyntaxError, KEYWORDS
from .parser import Parser, parse
from .runtime import Runtime, run_source

__all__ = [
    "Lexer", "Token", "JockySyntaxError", "KEYWORDS",
    "Parser", "parse", "Runtime", "run_source",
    "__version__", "LANG",
]
