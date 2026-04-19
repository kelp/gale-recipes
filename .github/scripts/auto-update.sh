#!/bin/bash
# Auto-update agent: checks upstream GitHub releases for
# every recipe, writes a status entry to _data/upstream.json,
# and (for recipes past the cooldown) opens a PR with the
# version bump.
#
# The dashboard generator reads _data/upstream.json to render
# "upstream X.Y.Z · Nd ago" pills. A recipe without a
# `source.repo` field is recorded as status="untracked".
set -uo pipefail

COOLDOWN_DAYS=3
FILTER="${1:-}"

# Output accumulator for _data/upstream.json. One JSON
# object per line, keyed by recipe name; collated after the
# main loop runs.
TMP_DIR=$(mktemp -d)
trap 'rm -rf "$TMP_DIR"' EXIT
NDJSON="$TMP_DIR/entries.ndjson"
: > "$NDJSON"

NOW_ISO=$(date -u '+%Y-%m-%dT%H:%M:%SZ')

# Space GitHub API calls out across the run (300–900 ms
# between recipes) so ~150 tracked recipes land over
# minutes rather than seconds.
jitter_sleep() {
  local n=$(( (RANDOM % 7) + 3 ))
  sleep "0.${n}"
}

# Append one recipe's upstream status to NDJSON. Fields
# beyond name/status/current are optional and omitted if
# empty, so the JSON stays compact.
emit_upstream() {
  local name="$1" status="$2"
  local current="${3:-}" latest="${4:-}"
  local released="${5:-}" url="${6:-}" reason="${7:-}"
  jq -cn \
    --arg name "$name" \
    --arg status "$status" \
    --arg current "$current" \
    --arg latest "$latest" \
    --arg released "$released" \
    --arg url "$url" \
    --arg reason "$reason" \
    --arg checked "$NOW_ISO" \
    '{($name): (
       {status: $status, current_version: $current, checked_at: $checked}
       + (if $latest   != "" then {latest_version: $latest}         else {} end)
       + (if $released != "" then {latest_released_at: $released}   else {} end)
       + (if $url      != "" then {latest_release_url: $url}        else {} end)
       + (if $reason   != "" then {reason: $reason}                 else {} end)
     )}' >> "$NDJSON"
}

check_recipe() {
  local file="$1"
  local name
  name=$(grep '^name' "$file" | head -1 | sed 's/.*= *"//' | sed 's/".*//')
  local version
  version=$(grep '^version' "$file" | head -1 | sed 's/.*= *"//' | sed 's/".*//')
  local repo
  repo=$(grep '^repo' "$file" | head -1 | sed 's/.*= *"//' | sed 's/".*//')
  local url
  url=$(grep '^url' "$file" | head -1 | sed 's/.*= *"//' | sed 's/".*//')

  if [ -z "$repo" ]; then
    echo "SKIP $name: no repo field"
    emit_upstream "$name" "untracked" "$version" "" "" "" \
      "no source.repo field"
    return
  fi

  jitter_sleep

  # Query latest release.
  local release_json
  release_json=$(gh api "/repos/${repo}/releases/latest" 2>/dev/null) || {
    echo "SKIP $name: no releases found for $repo"
    emit_upstream "$name" "untracked" "$version" "" "" "" \
      "no releases found on ${repo}"
    return
  }

  local new_tag
  new_tag=$(echo "$release_json" | jq -r '.tag_name')
  local published_at
  published_at=$(echo "$release_json" | jq -r '.published_at[:10]')

  local release_url="https://github.com/${repo}/releases/tag/${new_tag}"

  # Extract version from tag: strip v prefix, then name- prefix.
  local new_version="$new_tag"
  new_version="${new_version#v}"
  new_version="${new_version#"${name}-"}"

  if [ "$new_version" = "$version" ]; then
    echo "OK $name: up to date ($version)"
    emit_upstream "$name" "up_to_date" "$version" "$new_version" \
      "$published_at" "$release_url" ""
    return
  fi

  # New version detected. Record "outdated" regardless of
  # cooldown or PR state — the dashboard should reflect
  # reality even when we haven't proposed an upgrade yet.
  emit_upstream "$name" "outdated" "$version" "$new_version" \
    "$published_at" "$release_url" ""

  # Enforce cooldown for *PR creation* only.
  local now_epoch
  now_epoch=$(date +%s)
  local release_epoch
  release_epoch=$(date -d "$published_at" +%s 2>/dev/null || date -j -f "%Y-%m-%d" "$published_at" +%s 2>/dev/null)
  local age_days=$(( (now_epoch - release_epoch) / 86400 ))

  if [ "$age_days" -lt "$COOLDOWN_DAYS" ]; then
    echo "COOLDOWN $name: $new_version released $age_days days ago (need $COOLDOWN_DAYS)"
    return
  fi

  # Check for existing PR.
  local existing
  existing=$(gh pr list --search "auto-update ${name} ${new_version}" --json number --jq 'length')
  if [ "$existing" -gt 0 ]; then
    echo "SKIP $name: PR already exists for $new_version"
    return
  fi

  echo "UPDATE $name: $version -> $new_version (tag: $new_tag)"

  # Construct new URL by replacing old tag with new tag.
  local old_tag
  if echo "$url" | grep -q '/archive/refs/tags/'; then
    old_tag=$(echo "$url" | sed 's|.*/archive/refs/tags/||' | sed 's|\.tar\.gz$||')
  elif echo "$url" | grep -q '/releases/download/'; then
    old_tag=$(echo "$url" | sed 's|.*/releases/download/||' | sed 's|/.*||')
  else
    echo "ERROR $name: unrecognized URL pattern"
    return
  fi

  local new_url
  new_url=$(echo "$url" | sed "s|${old_tag}|${new_tag}|g")

  # Also replace old version in URL (for releases/download filenames).
  new_url=$(echo "$new_url" | sed "s|${version}|${new_version}|g")

  # Download and hash new tarball.
  local tmpfile
  tmpfile=$(mktemp)
  if ! curl -sL "$new_url" -o "$tmpfile"; then
    echo "ERROR $name: failed to download $new_url"
    rm -f "$tmpfile"
    return
  fi

  local filesize
  filesize=$(wc -c < "$tmpfile" | tr -d ' ')
  if [ "$filesize" -lt 1000 ]; then
    echo "ERROR $name: download too small (${filesize} bytes), likely 404"
    rm -f "$tmpfile"
    return
  fi

  local new_sha256
  new_sha256=$(shasum -a 256 "$tmpfile" | awk '{print $1}')
  rm -f "$tmpfile"

  # Update recipe TOML.
  sed -i.bak "s|^version = \"${version}\"|version = \"${new_version}\"|" "$file"
  sed -i.bak "s|^url = \"${url}\"|url = \"${new_url}\"|" "$file"
  sed -i.bak "s|^sha256 = \"[a-f0-9]*\"|sha256 = \"${new_sha256}\"|" "$file"
  sed -i.bak "s|^released_at = \"[0-9-]*\"|released_at = \"${published_at}\"|" "$file"

  # Remove stale binary sections.
  sed -i.bak '/^\[binary\./,/^$/d' "$file"

  # Clean up sed backup files.
  rm -f "${file}.bak"

  # Create PR.
  local branch="auto-update/${name}-${new_version}"
  git checkout -b "$branch"
  git add "$file"
  git commit -m "Update ${name} to ${new_version}"
  git push -u origin "$branch"
  gh pr create \
    --title "Update ${name} to ${new_version}" \
    --body "$(cat <<PRBODY
## Auto-update

- **Package:** ${name}
- **Version:** ${version} -> ${new_version}
- **Upstream:** https://github.com/${repo}/releases/tag/${new_tag}
- **Cooldown:** ${age_days} days since release

Binary sections removed — CI will rebuild and
repopulate them when this PR is merged.
PRBODY
)" \
    --label "auto-update"
  git checkout main

  echo "PR created for $name $new_version"
}

# Find recipes to check.
if [ -n "$FILTER" ]; then
  letter="${FILTER:0:1}"
  file="recipes/${letter}/${FILTER}.toml"
  if [ ! -f "$file" ]; then
    echo "Recipe not found: $file"
    exit 1
  fi
  check_recipe "$file"
else
  for file in recipes/*/*.toml; do
    check_recipe "$file" || true
  done
fi

# Collate NDJSON entries into _data/upstream.json. When
# FILTER is set we only ran one recipe — merge into any
# existing file rather than overwriting the full index.
mkdir -p _data
if [ -n "$FILTER" ] && [ -f _data/upstream.json ]; then
  jq -s --arg gen "$NOW_ISO" --slurpfile existing _data/upstream.json '
    {generated_at: $gen,
     recipes: (($existing[0].recipes // {}) + (add // {}))}
  ' "$NDJSON" > _data/upstream.json.new
else
  jq -s --arg gen "$NOW_ISO" '
    {generated_at: $gen, recipes: (add // {})}
  ' "$NDJSON" > _data/upstream.json.new
fi
mv _data/upstream.json.new _data/upstream.json
echo "Wrote _data/upstream.json ($(jq '.recipes | length' _data/upstream.json) recipes)"
