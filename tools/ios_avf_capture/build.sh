#!/bin/bash
# Build the native iOS AVFoundation capture helper.
# Usage & troubleshooting: docs/setup/ios_avf_capture.md
set -euo pipefail
cd "$(dirname "$0")"
OUT="${1:-ios-avf-capture}"
swiftc -O capture.swift -o "$OUT" \
  -framework AVFoundation \
  -framework CoreMediaIO \
  -framework CoreMedia \
  -framework CoreVideo \
  -framework VideoToolbox \
  -framework Foundation
echo "built: $(pwd)/$OUT"
