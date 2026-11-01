#!/bin/sh
# Stand-in for Audiveris in tests: "recognises" any input as the fixture score.
out=""
while [ $# -gt 0 ]; do
  case "$1" in -output) out="$2"; shift ;; esac
  shift
done
mkdir -p "$out/score"
cp "$(dirname "$0")/fixtures/piano.mxl" "$out/score/score.mxl"
echo "fake audiveris done"
