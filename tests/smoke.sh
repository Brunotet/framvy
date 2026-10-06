#!/usr/bin/env bash
# Fast sanity check (no browser): python -m editor.cli --dry-run on both examples.
set -e
cd "$(dirname "$0")/.."
python -m editor.cli --job examples/job_text_only.json --dry-run
python -m editor.cli --job examples/job_images.json --dry-run
python -m editor.cli --job examples/job_shader.json --dry-run
# script mode (narration + images) against fake Modal servers, no credits spent
python tests/mock_modal.py & MOCK=$!; sleep 2
MODAL_TTS_URL=http://127.0.0.1:8765/tts QWEN_IMAGE_URL=http://127.0.0.1:8765/img \
  python -m editor.cli --job examples/job_script.json --dry-run
kill $MOCK
echo "smoke OK"
