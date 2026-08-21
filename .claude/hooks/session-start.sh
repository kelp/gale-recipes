#!/usr/bin/env bash
# SessionStart hook: install the index-lint toolchain this container lacks.
#
# Async so the session starts immediately. scripts/agent-bootstrap.sh takes an
# flock, so re-running it blocks until the background run finishes — that, not
# a polling loop, is the wait contract. See docs/dev/agent-environment.md.

set -uo pipefail

echo '{"async": true, "asyncTimeout": 600000}'

exec "${CLAUDE_PROJECT_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}/scripts/agent-bootstrap.sh"
