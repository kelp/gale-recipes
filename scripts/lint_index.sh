#!/usr/bin/env bash
# Lint fetch-catalog files under index/.
#
# Layout is checked in-process (no gale). Schema lint uses
# `gale lint`, which must understand index documents (gale
# main at/after the index-lint change). A stale bootstrap
# gale failing here is an environment condition, not a
# catalog defect: rebuild with just update-gale.
#
# Zero index files: exit 0. Do not call gale with no args.
#
# INDEX_BASE, when set to a git ref that has index files,
# runs `gale lint --base` on modifications and refuses
# deletions. Additions are covered by `gale lint` on HEAD.

set -euo pipefail

here=$(cd "$(dirname "$0")" && pwd)
root=$(cd "${1:-.}" && pwd)
cd "$root"

PYTHONPATH="$here" python3 -c '
import sys
from pathlib import Path
import index_layout
issues = index_layout.issues(Path(sys.argv[1]))
if issues:
    print("\n".join(issues), file=sys.stderr)
    sys.exit(1)
' "$root"

mapfile -t files < <(find index -type f -name '*.toml' 2>/dev/null | sort || true)
if [ "${#files[@]}" -eq 0 ]; then
  echo "no index files"
  exit 0
fi

gale=${GALE:-gale}
command -v "$gale" >/dev/null || {
  echo "$gale not found — build gale from main (index lint) or set GALE" >&2
  exit 1
}

"$gale" lint "${files[@]}"

base=${INDEX_BASE:-}
if [ -z "$base" ]; then
  if git rev-parse --verify origin/main >/dev/null 2>&1; then
    base=origin/main
  fi
fi
if [ -z "$base" ]; then
  exit 0
fi

while IFS= read -r old; do
  [ -z "$old" ] && continue
  if [ ! -f "$old" ]; then
    echo "index file was removed: $old" >&2
    exit 1
  fi
  tmp=$(mktemp)
  git show "$base:$old" >"$tmp"
  "$gale" lint --base "$tmp" "$old"
  rm -f "$tmp"
done < <(git ls-tree -r --name-only "$base" -- index 2>/dev/null | grep '\.toml$' || true)
