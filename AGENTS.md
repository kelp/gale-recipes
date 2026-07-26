# AGENTS.md

Guidance for AI coding agents working in `gale-recipes`.
`CLAUDE.md` is the single source of truth; read it first.
Then read
[`docs/dev/agent-environment.md`](docs/dev/agent-environment.md)
before your first command — it covers the async toolchain
bootstrap (`just agent-bootstrap` blocks until it
finishes) and the sandbox limits behind rule 3.

Three rules are non-negotiable:

1. Prefer static linking for CLI tools where practical;
   never force it for libraries, language runtimes, or
   packages meant to be linked against. Details:
   CLAUDE.md "Linking Policy" and
   `docs/dev/linking-policy.md`.
2. Do not strip features or drop dependencies to make a
   build pass. If a dependency is missing, add a recipe
   for it.
3. Recipes cannot be built in an agent sandbox —
   `gale build` and `gale install` depend on hosts the
   egress policy blocks, and they fail slowly rather
   than fast. `gale lint` is the local gate; the real
   gate is CI's `verify.yml`. Never weaken a recipe to
   make something pass locally.
