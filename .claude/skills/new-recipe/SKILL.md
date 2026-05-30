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

## macOS rpath / verifiability

Goal: the installed binary is byte-identical to the
CI-built, SHA256'd, Sigstore-attested artifact. As of gale
0.16.3, install does NOT rewrite rpaths — gale bakes the
dependency-farm rpath at build time, and a package's own
broken `@rpath` refs are no longer auto-fixed. If a Mach-O
references `@rpath/lib<self>.dylib` with no resolving
`LC_RPATH`, dyld aborts and `scripts/check_install.py` fails
the build. Common in C/C++ recipes where a `bin/` tool (or a
`lib/<pkg>/` plugin) links a sibling dylib. Prefer, in order:

1. **Static-link to remove the dylib (preferred)** — no rpath
   to fix, most verifiable. E.g. cmake
   `-DENABLE_SHARED=OFF -DENABLE_STATIC=ON`, autotools
   `--disable-shared --enable-static`.
2. **Bake the rpath in a build step** (only when shared libs
   must ship), so it lands in the artifact before hashing —
   build-time, not install-time:
   `"for b in ${PREFIX}/bin/*; do [ -f \"$b\" ] || continue; file \"$b\" | grep -q Mach-O || continue; install_name_tool -add_rpath @loader_path/../lib \"$b\" 2>/dev/null || true; done"`
   See `recipes/o/openssl4.toml`, `recipes/p/postgresql.toml`.
3. **Never** use a post-install hook or rely on gale patching
   the binary on the user's machine — it breaks verification.

Full rationale: `docs/dev/linking-policy.md`.

## Batch Mode

To create multiple recipes at once, use the Agent tool
with subagent_type="programmer" and the recipe-creator
agent instructions. Launch up to 5 agents in parallel:

```
/new-recipe batch k9s helix age glow jless
```

This dispatches one agent per package.
