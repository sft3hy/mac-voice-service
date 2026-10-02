#!/usr/bin/env bash
# Download Kokoro-82M weights once so the service never fetches them at request time.
set -euo pipefail

cd "$(dirname "$0")/.."
VENV="${VENV:-.venv}"
DEST="${MODEL_DIR:-models/Kokoro-82M}"

if [ ! -x "$VENV/bin/python" ]; then
  echo ">> creating Python 3.12 venv (kokoro requires <3.13)"
  uv python install 3.12
  uv venv --python 3.12 "$VENV"
  uv pip install --python "$VENV/bin/python" -r gateway/requirements.txt \
    --extra-index-url https://download.pytorch.org/whl/cpu
fi

echo ">> downloading weights into $DEST"
HF_HUB_ENABLE_HF_TRANSFER=1 "$VENV/bin/python" - "$DEST" <<'PY'
import sys
from huggingface_hub import snapshot_download
path = snapshot_download("hexgrad/Kokoro-82M", local_dir=sys.argv[1])
print("weights ready:", path)
PY

du -sh "$DEST"
ls "$DEST"/kokoro-v1_0.pth >/dev/null && echo "OK: $(ls "$DEST"/voices/*.pt | wc -l) voices available"
