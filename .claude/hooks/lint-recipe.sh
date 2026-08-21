#!/usr/bin/env bash
# PostToolUse(Edit|Write): parse every .toml, and `gale lint`
# every index document. Leftover source recipes stay until
# Milestone 5; recipe lint is gone.
#
# Two bugs fixed relative to the inline version this replaces:
#
#   1. The glob was `recipes/*.toml`, which under bash [[ == ]] does not cross
#      a slash — so it never matched `recipes/g/git.toml` and the lint half of
#      this hook had never actually run on a real recipe.
#   2. It called `gale` unconditionally. In a fresh agent container gale is
#      installed by an async bootstrap, so every edit made in the first minute
#      of a session failed the hook. It is now skipped when gale is absent.

set -uo pipefail

file_path="$(jq -r '.file_path // .filePath // empty' 2>/dev/null <<<"${CLAUDE_TOOL_INPUT:-}")"
[ -n "$file_path" ] || exit 0
[ -f "$file_path" ] || exit 0

case "$file_path" in
  *.toml) ;;
  *) exit 0 ;;
esac

if ! python3 -c "import tomllib, sys; tomllib.load(open(sys.argv[1],'rb'))" "$file_path"; then
  echo "Invalid TOML syntax: $file_path" >&2
  exit 2
fi

case "$file_path" in
  *.binaries.toml) exit 0 ;;
  index/*/*.toml | */index/*/*.toml) ;;
  *) exit 0 ;;
esac

if ! command -v gale >/dev/null 2>&1; then
  echo "note: gale not on PATH yet (bootstrap may still be running); skipped 'gale lint $file_path'" >&2
  exit 0
fi

if ! gale lint "$file_path"; then
  exit 2
fi

exit 0
