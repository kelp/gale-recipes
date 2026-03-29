#!/usr/bin/env bash
# Sign all recipe TOML files with ed25519.
# Requires RECIPE_SIGNING_KEY env var (base64 private key).
set -euo pipefail

if [ -z "${RECIPE_SIGNING_KEY:-}" ]; then
  echo "::error::RECIPE_SIGNING_KEY not set"
  exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

find "$REPO_DIR/recipes" -name '*.toml' | while read -r FILE; do
  go run "$SCRIPT_DIR/sign-file.go" "$FILE"
  echo "Signed: $FILE"
done
