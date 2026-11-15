#!/usr/bin/env bash
# ContextFlow Web Runner
# Serves ContextFlow over web terminal with dark obsidian styling (#0d0e12) and HydraDB orange accents.

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
TARGET_SCRIPT="tui.py"

if [ "$1" = "textual" ] || [ "$1" = "--textual" ]; then
    TARGET_SCRIPT="tui_textual.py"
fi

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
echo " Target : $APP_DIR/$TARGET_SCRIPT"
echo " Port   : ${PORT}"
echo " Theme  : Obsidian Dark (#0d0e12) + HydraDB Orange (#FF5719)"
echo "=========================================================="

exec ttyd \
  -p "$PORT" \
  -i 0.0.0.0 \
  -W \
  -w "$APP_DIR" \
  -t fontSize=14 \
  -t fontFamily="ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace" \
  -t letterSpacing=0 \
  -t lineHeight=1.2 \
  -t cursorBlink=true \
  -t "theme={\"background\": \"#0d0e12\", \"foreground\": \"#eceff4\", \"cursor\": \"#FF5719\", \"selectionBackground\": \"#ff571933\"}" \
  "$PYTHON_BIN" "$APP_DIR/$TARGET_SCRIPT"
