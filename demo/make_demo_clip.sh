#!/usr/bin/env bash
# Creates a small synthetic test clip (video + 440 Hz tone) for trying EMAFIG without real evidence.
set -euo pipefail
cd "$(dirname "$0")"
ffmpeg -loglevel error -y -f lavfi -i testsrc=duration=6:size=640x360:rate=25 \
  -f lavfi -i sine=frequency=440:duration=6 \
  -c:v libx264 -pix_fmt yuv420p -c:a aac -shortest demo_clip.mp4
echo "Created $(pwd)/demo_clip.mp4"
