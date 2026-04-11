#!/usr/bin/env bash
set -euo pipefail

FILES=(README.md app.py requirements.txt)

for f in "${FILES[@]}"; do
  if [ -f "$f" ] && grep -Eq '^(<<<<<<<|=======|>>>>>>>)' "$f"; then
    echo "Conflict markers detected in $f -> restoring from current branch HEAD"
    git restore --source=HEAD -- "$f"
  else
    echo "No conflict markers in $f"
  fi
done

echo "Done. Current status:"
git status --short
