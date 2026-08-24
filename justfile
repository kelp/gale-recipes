# Lint index documents and workflows
lint:
    #!/usr/bin/env bash
    set -euo pipefail
    for tool in gale actionlint; do
      command -v "$tool" >/dev/null || {
        echo "$tool not found — run 'just agent-bootstrap'" >&2
        exit 1
      }
    done
    scripts/lint_index.sh .
    actionlint
    if command -v zizmor >/dev/null; then
      zizmor --offline .
    fi

# Install the agent-sandbox toolchain (gale, just, actionlint).
# Blocks until the background SessionStart bootstrap finishes,
# so it doubles as "wait for it".
# See docs/dev/agent-environment.md.
agent-bootstrap:
    scripts/agent-bootstrap.sh --force

# Show what the agent bootstrap installed, and what failed.
agent-status:
    @cat ~/.cache/gale-agent-bootstrap/status-recipes 2>/dev/null || echo "agent bootstrap has not run — try 'just agent-bootstrap'"

# Run unit tests for scripts/ (stdlib unittest).
test:
    python3 -m unittest discover -s scripts -p 'test_*.py' -v

# Update gale from the sibling checkout into ~/.local/bin.
update-gale:
    #!/usr/bin/env bash
    set -euo pipefail
    if [ ! -d ../gale/cmd/gale ]; then
      echo "update-gale: sibling ../gale checkout is missing" >&2
      exit 1
    fi
    mkdir -p "$HOME/.local/bin"
    (cd ../gale && go build -o "$HOME/.local/bin/gale" ./cmd/gale/)
