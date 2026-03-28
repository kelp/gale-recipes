# Lint recipes and workflows
lint:
    find recipes -name '*.toml' ! -name '*.binaries.toml' | xargs gale lint
    actionlint
