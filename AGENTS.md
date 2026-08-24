# AGENTS.md

Guidance for AI coding agents working in `gale-recipes`.
`CLAUDE.md` is the single source of truth; read it first.
Then read
[`docs/dev/agent-environment.md`](docs/dev/agent-environment.md)
before your first command — it covers the async toolchain
bootstrap (`just agent-bootstrap` blocks until it
finishes) and the sandbox limits.

Rules:

1. This repo is the fetch index. Gale does not
   compile packages and does not ship bottles. Do
   not add `[build]` recipes, ledgers, or promote /
   verify-build CI.
2. Do not invent `tree_digest`. Admission records it.
3. `gale install` cannot work in an agent sandbox.
   It fails slowly. `gale build` is gone. `just lint`
   and `just test` are the local gates. The real gate
   is CI's `test.yml` (`test` + `index-lint`) and
   `admit-darwin.yml`. Never weaken an index document
   to make something pass locally.
