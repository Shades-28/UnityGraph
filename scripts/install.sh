#!/usr/bin/env bash
# UnityGraph one-shot installer for macOS / Linux.
# Detects Python 3.11+, installs pipx if missing, installs unitygraph globally
# via pipx so it's available on PATH everywhere.

set -e

echo
echo "=== UnityGraph installer (macOS/Linux) ==="
echo

# 1. Detect Python 3.11+
PYTHON_CMD=""
for cmd in python3.13 python3.12 python3.11 python3 python; do
  if command -v "$cmd" >/dev/null 2>&1; then
    ver="$("$cmd" --version 2>&1 | awk '{print $2}')"
    major="${ver%%.*}"
    rest="${ver#*.}"
    minor="${rest%%.*}"
    if [ "$major" -ge 3 ] && [ "$minor" -ge 11 ]; then
      PYTHON_CMD="$cmd"
      echo "[ok] Found $cmd (version $ver)"
      break
    fi
  fi
done

if [ -z "$PYTHON_CMD" ]; then
  echo "[error] Python 3.11 or newer is required but was not found on PATH."
  echo
  echo "Install Python:"
  echo "  macOS:    brew install python@3.12"
  echo "  Ubuntu:   sudo apt install python3.12"
  echo "  Other:    https://www.python.org/downloads/"
  exit 1
fi

# 2. Make sure pip is current and pipx is installed
echo
echo "Installing pipx (Python's tool installer)..."
"$PYTHON_CMD" -m pip install --user --upgrade pip pipx >/dev/null 2>&1 || {
  echo "[error] pip / pipx install failed. Run \"$PYTHON_CMD -m pip install --user --upgrade pipx\" manually."
  exit 1
}
"$PYTHON_CMD" -m pipx ensurepath >/dev/null 2>&1 || true

# 3. Install unitygraph
echo
echo "Installing unitygraph..."
"$PYTHON_CMD" -m pipx install unitygraph --force

echo
echo "=== Done. ==="
echo
echo "Next:"
echo "  1. Restart your shell (so the pipx PATH update takes effect)"
echo "  2. cd into your Unity project"
echo "  3. Run: unitygraph init ."
echo "  4. Run: unitygraph build ."
echo
echo "No Unity project handy? Try the bundled demo:"
echo "  unitygraph init --demo my-demo"
echo "  cd my-demo"
echo "  unitygraph build ."
echo "  unitygraph viz graph-out/graph.json"
echo
