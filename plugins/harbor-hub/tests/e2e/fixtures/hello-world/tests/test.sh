#!/bin/bash
# Reward file is authoritative; always write it and exit 0.
if [ "$(cat /app/hello.txt 2>/dev/null)" = "Hello, world!" ]; then
  echo "PASS: /app/hello.txt has the expected content"
  echo 1 > /logs/verifier/reward.txt
else
  echo "FAIL: /app/hello.txt missing or wrong content"
  echo 0 > /logs/verifier/reward.txt
fi
