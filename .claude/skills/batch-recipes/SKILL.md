---
name: batch-recipes
description: Create multiple gale recipes in parallel
disable-model-invocation: true
---

# Batch Recipes

Create multiple gale recipes by dispatching parallel
agents. Each agent uses the recipe-creator pattern.

## Usage

`/batch-recipes <name1> <name2> <name3> ...`

## Behavior

1. Check which packages already have recipes (skip them)
2. Dispatch up to 5 `recipe-creator` agents in parallel,
   each creating one recipe
3. As agents complete, lint each recipe with `gale lint`
4. When all agents finish, commit and push

## Agent Prompt Template

Each agent receives this prompt (with <name> replaced):

```
Create a gale recipe for <name>.

1. Run: `gale import homebrew <name>` for a starting point
2. Check the GitHub repo for latest release, build system
3. Get sha256: `curl -sL <url> | shasum -a 256`
4. Write to recipes/<letter>/<name>.toml (repo-relative)
5. Run `gale lint` on the recipe

Patterns — see .claude/agents/recipe-creator.md.
No [binary.*] sections. Add repo field for auto-update.
```

## Example

```
/batch-recipes gdu bottom stylua shellcheck
```

Dispatches 4 agents, each creating one recipe.
