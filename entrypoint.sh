#!/bin/sh
# Container entrypoint — launch merchant (loopback) and Streamlit (public).
set -e

PORT="${PORT:-8080}"

# Merchant runs on 127.0.0.1:8001 inside the container — invisible from outside.
uv run --no-sync python -m uvicorn services.merchant.main:app \
  --host 127.0.0.1 \
  --port 8001 \
  --log-level warning \
  &
MERCHANT_PID=$!

# Trap signals so the background merchant exits cleanly with the container.
trap 'kill -TERM "$MERCHANT_PID" 2>/dev/null || true' INT TERM

# Briefly wait for merchant readiness so the first UI render doesn't error.
for _ in 1 2 3 4 5 6 7 8 9 10; do
  if python -c "import urllib.request, sys; urllib.request.urlopen('http://127.0.0.1:8001/healthz', timeout=1)" >/dev/null 2>&1; then
    echo "merchant ready"
    break
  fi
  sleep 1
done

# Streamlit on Cloud Run needs:
#  - bind to 0.0.0.0
#  - use $PORT
#  - headless
#  - XSRF off (Cloud Run sits behind proxies; the default check 400s WebSocket upgrades)
exec uv run --no-sync python -m streamlit run ui/app.py \
  --server.address 0.0.0.0 \
  --server.port "$PORT" \
  --server.headless true \
  --browser.gatherUsageStats false \
  --server.enableCORS true \
  --server.enableXsrfProtection false
