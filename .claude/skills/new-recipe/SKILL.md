---
name: new-recipe
description: Scaffold a new gale recipe TOML file from a GitHub repo
disable-model-invocation: true
---

# New Recipe

Create a new gale recipe TOML file for a package.

## Usage

`/new-recipe <github-org/repo>` or `/new-recipe <name>`

## Steps

1. Run `gale import homebrew <name>` for a starting point
2. Check GitHub repo for latest release, build system,
   and dependencies
3. Get source sha256:
   `curl -sL <url> | shasum -a 256`
4. Write recipe to `recipes/<first-letter>/<name>.toml`
5. Run `gale lint` on the recipe

## Build Patterns

See `.claude/agents/recipe-creator.md` for the full
pattern reference (Cargo, Go, Autotools, cmake).

## Key Rules

- Add `repo = "owner/repo"` for auto-update
- Add `released_at` from GitHub release date
- Do NOT include `[binary.*]` sections (CI adds those)
- Do NOT strip features to avoid dependencies
- For Cargo workspaces, check for virtual manifests
  and use `--path <crate-dir>` instead of `--path .`
- Build variables: `${PREFIX}`, `${VERSION}`, `${JOBS}`,
  `${OS}`, `${ARCH}`, `${PLATFORM}`

## Batch Mode

To create multiple recipes at once, use the Agent tool
with subagent_type="programmer" and the recipe-creator
agent instructions. Launch up to 5 agents in parallel:

```
/new-recipe batch k9s helix age glow jless
```

This dispatches one agent per package.
