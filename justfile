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
