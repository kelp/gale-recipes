# AGENTS.md

Guidance for AI coding agents working in `gale-recipes`.
`CLAUDE.md` is the single source of truth; read it first.
Two rules are non-negotiable:

1. Prefer static linking for CLI tools where practical;
   never force it for libraries, language runtimes, or
   packages meant to be linked against. Details:
   CLAUDE.md "Linking Policy" and
   `docs/dev/linking-policy.md`.
2. Do not strip features or drop dependencies to make a
   build pass. If a dependency is missing, add a recipe
   for it.
