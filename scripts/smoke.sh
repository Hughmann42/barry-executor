#!/usr/bin/env bash
set -euo pipefail
URL="${1:-http://127.0.0.1:8000/health}"
echo "GET $URL"
curl -sS "$URL" | python - <<'PY'
import sys, json
s = sys.stdin.read()
try:
    d = json.loads(s)
    print("Health OK" if d.get("ok") else "Health FAIL", d)
except Exception as e:
    print("Bad response:", s[:200])
    raise
PY
