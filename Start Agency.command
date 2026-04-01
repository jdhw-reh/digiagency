#!/bin/bash
# Double-click this file to start Digi Agency and open it in your browser

DIR="$(cd "$(dirname "$0")" && pwd)"

# Check Redis is running; start it if not
if ! redis-cli ping &>/dev/null; then
  echo "Starting Redis..."
  brew services start redis
  sleep 1
fi

# Start the server in the background
echo "Starting Digi Agency server..."
"$DIR/venv/bin/uvicorn" main:app --host 127.0.0.1 --port 8000 --app-dir "$DIR" &
SERVER_PID=$!

# Wait for server to be ready
echo "Waiting for server to start..."
for i in {1..20}; do
  if curl -s http://127.0.0.1:8000 &>/dev/null; then
    break
  fi
  sleep 0.5
done

# Open in default browser
open http://127.0.0.1:8000

echo "Digi Agency is running at http://127.0.0.1:8000"
echo "Close this window to stop the server."

# Keep script alive so closing Terminal stops the server
wait $SERVER_PID
