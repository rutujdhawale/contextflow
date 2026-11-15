#!/usr/bin/env bash
# ContextFlow Web Runner
# Serves ContextFlow Dual-Panel Data Hub & Terminal over port $PORT (default 10000).

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
    fuser -k "7682/tcp" 2>/dev/null || true
elif command -v lsof >/dev/null 2>&1; then
    PIDS=$(lsof -ti :"$PORT",:7682 2>/dev/null || true)
    if [ -n "$PIDS" ]; then
        kill -9 $PIDS 2>/dev/null || true
    fi
fi

# Small grace period for socket release
sleep 0.2

export TTY_ATTACHED=1

echo "=========================================================="
echo " Starting ContextFlow Web Gateway & Data Hub"
echo " Port   : ${PORT}"
echo " Theme  : Obsidian Dark (#0b0c10) + HydraDB Orange (#FF5719)"
echo " Layout : Split Terminal (72%) + Drag & Drop Uploader (28%)"
echo "=========================================================="

# If user explicitly asks for direct terminal only:
if [ "$1" = "direct" ] || [ "$1" = "--direct" ]; then
    exec ttyd \
      -p "$PORT" \
      -i 0.0.0.0 \
      -W \
      -w "$APP_DIR" \
      -t fontSize=14 \
      -t fontFamily="ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace" \
      -t letterSpacing=0 \
      -t lineHeight=1.2 \
      -t "theme={\"background\": \"#0b0c10\", \"foreground\": \"#eceff4\", \"cursor\": \"#FF5719\"}" \
      "$PYTHON_BIN" "$APP_DIR/tui.py"
fi

# Default: Launch full Web Gateway with Terminal + Drag-and-Drop Auto-Snapshot builder
exec "$PYTHON_BIN" "$APP_DIR/web_server.py"
