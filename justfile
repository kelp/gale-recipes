# Lint recipes and workflows
lint:
    gale lint recipes/**/*.toml
    actionlint

# Update gale from source (sibling repo)
update-gale:
    gale install gale --source ../gale -g
