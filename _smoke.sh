#!/bin/bash
set -e
BASE="${1:-https://web-production-27d0.up.railway.app}"

passfail () { local name="$1" code="$2"; if [ "$code" = "200" ]; then echo "$name: PASS"; else echo "$name: FAIL ($code)"; fi; }

# health/root
code=$(curl -s -o /dev/null -w "%{http_code}" "$BASE/");             passfail "ROOT" "$code"
code=$(curl -s -o /dev/null -w "%{http_code}" "$BASE/healthz");      passfail "HEALTHZ" "$code"
code=$(curl -s -o /dev/null -w "%{http_code}" "$BASE/health");       passfail "HEALTH" "$code"

# account/bars (these require Alpaca creds set in env)
code=$(curl -s -o /dev/null -w "%{http_code}" "$BASE/account");      passfail "ACCOUNT" "$code"
code=$(curl -s -o /dev/null -w "%{http_code}" "$BASE/bars?symbol=AAPL&timeframe=15Min&limit=5"); passfail "BARS" "$code"

# intent dry-run using V1 HMAC signature
SECRET="${SHARED_SECRET:-}"
if [ -z "$SECRET" ]; then echo "INTENT: SKIP (no SHARED_SECRET in env for local test)"; exit 0; fi
body='{"symbol":"AAPL","side":"buy","qty":1,"dry_run":true}'
sig=$(python3 - <<PY
import os,hashlib,hmac,sys,json
secret=os.environ.get("SHARED_SECRET","")
body='{"symbol":"AAPL","side":"buy","qty":1,"dry_run":true}'
print(hmac.new(secret.encode(), body.encode(), hashlib.sha256).hexdigest())
PY
)
code=$(curl -s -o /dev/null -w "%{http_code}" -X POST "$BASE/intent" \
  -H "Content-Type: application/json" -H "X-Signature: $sig" -d "$body")
passfail "INTENT(dry_run)" "$code"
