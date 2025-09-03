#!/bin/bash
set -euo pipefail
BASE="${BASE:-https://web-production-27d0.up.railway.app}"
SECRET="${BARRY_SHARED_SECRET:?set BARRY_SHARED_SECRET in env}"

sign(){ printf '%s' "$1" | openssl dgst -sha256 -hmac "$SECRET" -r | awk '{print $1}'; }

echo "== /health =="; curl -sS -i "$BASE/health"; echo; echo
echo "== /snapshot =="; curl -sS -i "$BASE/snapshot?symbol=AAPL"; echo; echo
echo "== /bars =="; curl -sS -i "$BASE/bars?symbol=AAPL&tf=15m&limit=5"; echo; echo

payload='{"symbol":"AAPL","side":"buy","type":"market","notional":200,"time_in_force":"day","dry_run":true,"client_id":"BBB-DRYRUN","meta":{"source":"bbb_probe"}}'
sig=$(sign "$payload")
echo "== /intent (dry_run) =="; curl -sS -i -X POST "$BASE/intent" -H "Content-Type: application/json" -H "X-Signature: $sig" --data-raw "$payload"; echo
