#!/usr/bin/env bash
# Oracle for the calendar task. The expected date moves with the clock, so the oracle
# computes it the same way the verifier does rather than echoing a literal.
set -euo pipefail
APP_DIR="${APP_DIR:-/app}"
mkdir -p "$APP_DIR"
python3 - "$APP_DIR/answer.json" <<'PY'
import json, sys
from datetime import date, timedelta
answer = (date.today() + timedelta(days=9)).isoformat()
with open(sys.argv[1], "w") as fh:
    json.dump({"next_release_date": answer}, fh)
PY
