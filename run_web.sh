#!/usr/bin/env bash
# ContextFlow Web Runner
# Serves ContextFlow over web terminal with dark obsidian styling (#0b0c10) and HydraDB orange accents.

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

PORT="${PORT:-7681}"
TARGET_SCRIPT="tui.py"

if [ "$1" = "textual" ] || [ "$1" = "--textual" ]; then
    TARGET_SCRIPT="tui_textual.py"
fi

echo "=========================================================="
echo " Starting ContextFlow Web Terminal"
echo " Target : $APP_DIR/$TARGET_SCRIPT"
echo " URL    : http://127.0.0.1:${PORT}"
echo " Theme  : Obsidian Dark (#0b0c10) + HydraDB Orange (#FF5719)"
echo "=========================================================="

exec ttyd \
  -p "$PORT" \
  -W \
  -w "$APP_DIR" \
  -t fontSize=15 \
  -t fontFamily="'Fira Code', 'JetBrains Mono', 'DejaVu Sans Mono', monospace" \
  -t "theme={\"background\": \"#0b0c10\", \"foreground\": \"#eceff4\", \"cursor\": \"#FF5719\", \"selectionBackground\": \"#ff571933\"}" \
  "$PYTHON_BIN" "$APP_DIR/$TARGET_SCRIPT"
