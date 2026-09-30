#!/usr/bin/env sh
# JOCKY launcher — Linux / macOS / WSL
#
#   ./run.sh              start the console at http://127.0.0.1:8787
#   ./run.sh --demo       run every script in the terminal instead
#   ./run.sh --test       run the test suite
#   ./run.sh --port 9000  use a different port

set -eu

cd "$(dirname "$0")"

PYTHON=""
for candidate in python3 python; do
    if command -v "$candidate" >/dev/null 2>&1; then
        PYTHON="$candidate"
        break
    fi
done

if [ -z "$PYTHON" ]; then
    printf '\n  Python 3.8+ was not found on PATH.\n'
    printf '  Debian/Ubuntu:  sudo apt install python3\n\n'
    exit 1
fi

printf '\n  JOCKY  forensic scripting language\n'
printf '  interpreter: %s (%s)\n\n' "$PYTHON" "$("$PYTHON" --version 2>&1)"

MODE="serve"
PORT=8787

while [ $# -gt 0 ]; do
    case "$1" in
        --demo) MODE="demo" ;;
        --test) MODE="test" ;;
        --port) shift; PORT="${1:-8787}" ;;
        *) printf '  unknown option: %s\n' "$1"; exit 2 ;;
    esac
    shift
done

case "$MODE" in
    test)
        exec "$PYTHON" -m unittest discover -s tests -t . -v
        ;;
    demo)
        for script in scripts/*.jky; do
            printf '========================================================================\n'
            printf '  %s\n' "$(basename "$script")"
            printf '========================================================================\n'
            "$PYTHON" -m jocky run "$script" || true
        done
        ;;
    serve)
        printf '  starting console on http://127.0.0.1:%s\n\n' "$PORT"
        if command -v xdg-open >/dev/null 2>&1; then
            (sleep 2 && xdg-open "http://127.0.0.1:$PORT/" >/dev/null 2>&1 &) || true
        fi
        exec "$PYTHON" -m jocky serve --port "$PORT"
        ;;
esac
