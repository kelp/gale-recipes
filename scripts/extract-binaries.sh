#!/usr/bin/env bash
#
# Extract [binary.<platform>] sections from recipe TOML files
# into separate .binaries.toml files, then strip them from
# the recipes.
#
# Usage: scripts/extract-binaries.sh
#
# Idempotent: skips recipes with no binary sections,
# overwrites existing .binaries.toml files.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
RECIPES_DIR="${REPO_ROOT}/recipes"

count=0

for recipe in "${RECIPES_DIR}"/*/*.toml; do
  # Skip .binaries.toml files
  case "$recipe" in
    *.binaries.toml) continue ;;
  esac

  # Skip recipes with no binary sections
  if ! grep -q '^\[binary\.' "$recipe"; then
    continue
  fi

  dir="$(dirname "$recipe")"
  base="$(basename "$recipe" .toml)"
  binaries_file="${dir}/${base}.binaries.toml"

  # Extract version from [package] section
  version=$(awk -F'"' '/^version *= *"/ {print $2; exit}' "$recipe")
  if [ -z "$version" ]; then
    echo "WARN: no version found in $recipe, skipping"
    continue
  fi

  # Extract platform + sha256 pairs from [binary.*] sections
  # Outputs lines like: darwin-arm64 <sha256>
  pairs=$(awk '
    /^\[binary\./ {
      # Extract platform name from [binary.platform-name]
      sub(/^\[binary\./, "")
      sub(/\]$/, "")
      # Remove quotes if present
      gsub(/"/, "")
      platform = $0
      next
    }
    platform && /^sha256 *= *"/ {
      # Extract sha256 value
      split($0, a, "\"")
      print platform " " a[2]
      platform = ""
    }
    # Reset on next section that is not binary
    /^\[/ && !/^\[binary\./ { platform = "" }
  ' "$recipe")

  if [ -z "$pairs" ]; then
    echo "WARN: binary sections found but no sha256 extracted from $recipe"
    continue
  fi

  # Write .binaries.toml
  {
    printf 'version = "%s"\n' "$version"
    echo "$pairs" | while read -r platform sha256; do
      printf '\n[%s]\nsha256 = "%s"\n' "$platform" "$sha256"
    done
  } > "$binaries_file"

  # Strip [binary.*] sections and trailing blank lines from recipe
  awk '
    /^\[binary\./ { skip = 1; next }
    skip && /^\[/ { skip = 0 }
    skip { next }
    { lines[++n] = $0 }
    END {
      # Remove trailing blank lines
      while (n > 0 && lines[n] == "") n--
      for (i = 1; i <= n; i++) print lines[i]
    }
  ' "$recipe" > "${recipe}.tmp" && mv "${recipe}.tmp" "$recipe"

  count=$((count + 1))
  echo "Extracted: ${base}.binaries.toml (${version})"
done

echo ""
echo "Done. Extracted binaries from ${count} recipes."
