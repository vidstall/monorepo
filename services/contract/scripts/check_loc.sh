#!/usr/bin/env bash
set -euo pipefail

MAX_LINES=200
cd "$(dirname "${BASH_SOURCE[0]}")/.."

status=0
while IFS= read -r -d '' file; do
    lines=$(wc -l < "$file")
    if [ "$lines" -gt "$MAX_LINES" ]; then
        echo "FAIL: $file has $lines lines (max $MAX_LINES)"
        status=1
    fi
done < <(find sources tests -type f -name '*.move' -print0)

if [ "$status" -eq 0 ]; then
    echo "OK: all .move files are within $MAX_LINES lines"
fi

exit "$status"
