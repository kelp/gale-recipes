#!/usr/bin/env bash
# One-time correction: re-pin each recipe's LATEST .versions entry to
# the commit that actually holds its matching binaries.
#
# Historical .versions entries were written pointing at the recipe-bump
# commit (and an old single-commit CI, plus the `4a5ad3a` "embed
# revision suffix" .binaries.toml format change) desynced them from the
# binary commit. The gale client's commit-pin resolver fetches
# binaries@<pinned-sha>; when that tree predates the version's binary,
# it silently source-builds. This corrects the latest entry — the only
# one the client resolves (pickLatest). Older entries are status-page
# history; their binaries were overwritten and are unrecoverable, so
# they are left untouched.
#
# The target SHA is the last commit touching <recipe>.binaries.toml,
# verified to carry both recipe==version and binaries==version. Recipes
# with no binary history (source-only) are skipped.
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"

fixed=0
skipped=0
for vf in $(git ls-files 'recipes/*/*.versions'); do
	base="${vf%.versions}"
	binrel="${base}.binaries.toml"
	recrel="${base}.toml"

	line=$(grep -v '^[[:space:]]*$' "$vf" | tail -1)
	ver=$(echo "$line" | awk '{print $1}')
	oldsha=$(echo "$line" | awk '{print $2}')
	[ -z "$ver" ] && continue

	cand=$(git log -1 --format=%H -- "$binrel" 2>/dev/null || true)
	if [ -z "$cand" ]; then
		skipped=$((skipped + 1))
		continue
	fi

	binver=$(git show "$cand:$binrel" 2>/dev/null |
		grep '^version' | head -1 | sed 's/.*= *"//; s/".*//' || true)
	rv=$(git show "$cand:$recrel" 2>/dev/null |
		grep '^version' | head -1 | sed 's/.*= *"//; s/".*//' || true)
	rr=$(git show "$cand:$recrel" 2>/dev/null |
		grep '^revision' | head -1 | sed 's/.*= *//; s/[^0-9].*//' || true)
	[ -z "$rr" ] && rr=1
	if [ "$rr" -le 1 ]; then rkey="$rv"; else rkey="${rv}-${rr}"; fi

	if [ "$binver" != "$ver" ] || [ "$rkey" != "$ver" ]; then
		echo "SKIP ${base##*/}: rule mismatch (bin='$binver' recipe='$rkey' want='$ver')" >&2
		skipped=$((skipped + 1))
		continue
	fi

	if [ "$oldsha" = "$cand" ]; then
		continue
	fi

	# Rewrite only the final entry's SHA in place.
	tmp=$(mktemp)
	awk -v want="$ver" -v sha="$cand" '
		{ lines[NR] = $0 }
		END {
			for (i = 1; i <= NR; i++) {
				split(lines[i], f, " ")
				if (i == NR && f[1] == want) {
					print f[1] " " sha
				} else {
					print lines[i]
				}
			}
		}
	' "$vf" >"$tmp"
	mv "$tmp" "$vf"
	echo "FIX ${base##*/}: $ver ${oldsha:0:7} -> ${cand:0:7}"
	fixed=$((fixed + 1))
done

echo "---"
echo "fixed=$fixed skipped=$skipped"
