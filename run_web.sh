#!/usr/bin/env bash
# ContextFlow Web Runner
# Serves ContextFlow Terminal UI directly on $PORT (default 10000).

set -e

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [ -d "$DIR/ContextFlow" ]; then
    APP_DIR="$DIR/ContextFlow"
else
    APP_DIR="$DIR"
fi

cd "$APP_DIR"

PYTHON_BIN="$APP_DIR/.venv/bin/python"
if [ ! -f "$PYTHON_BIN" ]; then
    PYTHON_BIN="python3"
fi

PORT="${PORT:-10000}"

# Clean up any lingering process on the target port to prevent (-1 98) EADDRINUSE
if command -v fuser >/dev/null 2>&1; then
    fuser -k "${PORT}/tcp" 2>/dev/null || true
elif command -v lsof >/dev/null 2>&1; then
    PIDS=$(lsof -ti :"$PORT" 2>/dev/null || true)
    if [ -n "$PIDS" ]; then
        kill -9 $PIDS 2>/dev/null || true
    fi
fi

# Small grace period for socket release
sleep 0.2

export TTY_ATTACHED=1

echo "=========================================================="
echo " Starting ContextFlow Web Terminal"
echo " Port   : ${PORT}"
echo " Theme  : Obsidian Dark (#0b0c10) + HydraDB Orange (#FF5719)"
echo " Layout : Pure Terminal (Full Screen, Left Aligned)"
echo "=========================================================="

exec ttyd \
  -p "$PORT" \
  -i 0.0.0.0 \
  -W \
  -w "$APP_DIR" \
  -t fontSize=16 \
  -t fontFamily="ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, 'Liberation Mono', monospace" \
  -t letterSpacing=0 \
  -t lineHeight=1.25 \
  -t "theme={\"background\": \"#090a0f\", \"foreground\": \"#f0f2f8\", \"cursor\": \"#FF5719\", \"selectionBackground\": \"#ff571933\"}" \
  "$PYTHON_BIN" "$APP_DIR/tui.py"
