# Lint recipes and workflows
lint:
    gale lint recipes/**/*.toml
    actionlint

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
