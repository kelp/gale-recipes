# Lint recipes and workflows
lint:
    gale lint recipes/**/*.toml
    actionlint

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
