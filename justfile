# Lint recipes and workflows
lint:
    #!/usr/bin/env bash
    set -euo pipefail
    for tool in gale actionlint; do
      command -v "$tool" >/dev/null || {
        echo "$tool not found — run 'just agent-bootstrap'" >&2
        exit 1
      }
    done
    gale lint recipes/**/*.toml
    # Index lint needs gale from main at/after the
    # index-document dispatch. A stale bootstrap binary
    # failing here is an environment condition: run
    # `just update-gale`. Zero files is a no-op.
    scripts/lint_index.sh .
    actionlint

# Install the agent-sandbox toolchain (gale, just, actionlint).
# Blocks until the background SessionStart bootstrap finishes,
# so it doubles as "wait for it".
# See docs/dev/agent-environment.md.
agent-bootstrap:
    scripts/agent-bootstrap.sh --force

# Show what the agent bootstrap installed, and what failed.
agent-status:
    @cat ~/.cache/gale-agent-bootstrap/status-recipes 2>/dev/null || echo "agent bootstrap has not run — try 'just agent-bootstrap'"

# Check a built/installed package: scan Mach-O/ELF files
# and verify every gale store path referenced is declared
# as a runtime dep. Pass either --prefix or --archive.
# Example:
#   just check-install recipes/g/git.toml \
#     --prefix ~/.gale/pkg/git/2.53.0
check-install recipe *ARGS:
    python3 scripts/check_install.py --recipe {{recipe}} {{ARGS}}

# Run a recipe's [smoke] commands against the installed
# package. Install the recipe first via gale install.
# Example: just smoke recipes/g/git.toml
smoke recipe *ARGS:
    python3 scripts/run_smoke.py --recipe {{recipe}} {{ARGS}}

# Generate the static build-status dashboard into _site/.
gen-pages:
    python3 scripts/gen_status_page.py --repo-root . --out-dir _site

# Run unit tests for scripts/ (stdlib unittest).
test:
    python3 -m unittest discover -s scripts -p 'test_*.py' -v

# Serve the generated dashboard at http://localhost:8000/.
# Run `just gen-pages` first.
serve-pages:
    python3 -m http.server -d _site 8000

# Update gale from source (sibling repo).
# Falls back to building from source if gale isn't
# installed or is too old to have the update command.
update-gale:
    #!/usr/bin/env sh
    if command -v gale >/dev/null 2>&1 && gale update gale --path ../gale; then
        exit 0
    fi
    echo "Bootstrapping gale from source..."
    cd ../gale && go build -o /tmp/gale-bootstrap ./cmd/gale/
    /tmp/gale-bootstrap install gale --path ../gale
    rm -f /tmp/gale-bootstrap
