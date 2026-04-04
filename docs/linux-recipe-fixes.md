# Linux Recipe Fixes

Recipes that build on macOS but fail on Linux. These
rely on headers or tools provided by the macOS SDK
without declaring equivalent gale dependencies.

Tested on Ubuntu 24.04 arm64 (OrbStack VM) with gale
built from source. All failures reproduce on
linux-amd64 too — none are arm64-specific.

## How to Test

```sh
# Cross-compile gale
GOOS=linux GOARCH=arm64 CGO_ENABLED=0 go build \
  -o /tmp/gale-linux ./cmd/gale

# Push to VM and install
orb push -m ubuntu-24.04 /tmp/gale-linux /tmp/gale
orb -m ubuntu-24.04 sudo install /tmp/gale \
  /usr/local/bin/gale

# Build a recipe
orb -m ubuntu-24.04 gale build \
  /path/to/recipes/j/jq.toml \
  --recipes=/path/to/gale-recipes

# Verbose output for debugging
orb -m ubuntu-24.04 gale build -v \
  /path/to/recipes/j/jq.toml \
  --recipes=/path/to/gale-recipes
```

Install system build tools first:

```sh
orb -m ubuntu-24.04 sudo apt-get install -y \
  build-essential curl git patchelf pkg-config \
  libssl-dev python3 unzip m4
```

## Category 1: Missing System Library Dependencies

These recipes use C libraries that macOS SDK provides
but Linux requires as declared gale build dependencies.

### Missing zlib

Cargo crates using `libz-sys` fail with:
`The system library "zlib" required by crate
"libz-sys" was not found.`

**Fix**: Add `"zlib"` to `[dependencies.build]`.

| Recipe | File |
|--------|------|
| gping | `recipes/g/gping.toml` |
| lsd | `recipes/l/lsd.toml` |
| gitui | `recipes/g/gitui.toml` |
| ouch | `recipes/o/ouch.toml` |
| zellij | `recipes/z/zellij.toml` |
| rustup | `recipes/r/rustup.toml` |
| tree-sitter | `recipes/t/tree-sitter.toml` |

### Missing ncurses

Configure scripts fail with:
`cannot find required curses/ncurses library`

**Fix**: Add `"ncurses"` to `[dependencies.build]`
or `[dependencies.runtime]` as appropriate.

| Recipe | File |
|--------|------|
| htop | `recipes/h/htop.toml` |
| less | `recipes/l/less.toml` |
| tmux | `recipes/t/tmux.toml` |
| tig | `recipes/t/tig.toml` |

### Missing other system deps

| Recipe | File | Missing | Error |
|--------|------|---------|-------|
| pigz | `recipes/p/pigz.toml` | zlib | `CC=cc` + missing zlib.h |
| mosh | `recipes/m/mosh.toml` | protobuf, ncurses | configure fails |
| nmap | `recipes/n/nmap.toml` | openssl, lua | make fails |
| zsh | `recipes/z/zsh.toml` | ncurses | configure fails |
| mariadb | `recipes/m/mariadb.toml` | ncurses, others | cmake fails |
| postgresql | `recipes/p/postgresql.toml` | flex, bison | meson setup fails |

## Category 2: Missing Python/pip

These recipes call `pip install` but don't declare
Python as a build dependency, or Python's pip isn't
on the isolated build PATH.

**Fix**: Add `"python"` to `[dependencies.build]`.
Verify that gale's build PATH includes python's
bin directory so `pip` is found.

| Recipe | File |
|--------|------|
| glances | `recipes/g/glances.toml` |
| httpie | `recipes/h/httpie.toml` |
| yt-dlp | `recipes/y/yt-dlp.toml` |

## Category 3: Ruby Gem Builds

`gem build *.gemspec` fails. These recipes depend on
Ruby but the gem tooling may not work correctly in
gale's isolated build environment.

**Fix**: Verify Ruby recipe provides working `gem`
command. Check if the gemspec has runtime dependencies
that need resolving.

| Recipe | File |
|--------|------|
| cocoapods | `recipes/c/cocoapods.toml` |
| colorls | `recipes/c/colorls.toml` |
| tmuxinator | `recipes/t/tmuxinator.toml` |

## Category 4: Gale Bugs

These require changes to the gale CLI, not recipes.

### `env` key in `[build]` section (helix)

`recipes/h/helix.toml` uses:

```toml
[build]
env = { HELIX_DEFAULT_RUNTIME = "${PREFIX}/lib/..." }
```

Gale's recipe parser rejects the `env` key with:
`unrecognized build key "env": expected platform in
os-arch format`

**Fix**: Add `Env map[string]string` to the `Build`
struct in `internal/recipe/recipe.go`. Parse it in
the TOML decoder. Pass env vars to the build shell
in `internal/build/build.go` alongside existing vars
like `PREFIX`, `JOBS`, etc.

### Symlink to `/dev/null` in tar archive (helm)

`recipes/h/helm.toml` source tarball contains:
`helm-4.1.3/.../null -> /dev/null`

Gale's tar extractor rejects this as a security
measure (absolute symlink target).

**Fix**: Allow symlinks to well-known safe targets
like `/dev/null` in `internal/download/extract.go`,
or add a recipe-level override.

## Category 5: Source/Build Issues

These need individual investigation.

| Recipe | File | Error | Notes |
|--------|------|-------|-------|
| docker | `recipes/d/docker.toml` | `go.mod not found` | Source archive structure changed |
| mandoc | `recipes/m/mandoc.toml` | make fails | Needs investigation |
| mtr | `recipes/m/mtr.toml` | `bootstrap.sh` exit 127 | Missing autotools dep |
| podman | `recipes/p/podman.toml` | make fails | Needs investigation |
| vibeutils | `recipes/v/vibeutils.toml` | mandoc dep fails | Blocked by mandoc fix |
| zf | `recipes/z/zf.toml` | zig build fails | Needs investigation |

## Category 6: Darwin-Only Recipes (Tier 3)

These 5 recipes failed in the Tier 3 darwin-only
testing. They have generic `[build]` sections but
fail on Linux.

| Recipe | File | Error |
|--------|------|-------|
| btop | `recipes/b/btop.toml` | Needs C++23 `std::ranges::to` (GCC 13 too old) |
| git | `recipes/g/git.toml` | Missing zlib dep |
| jless | `recipes/j/jless.toml` | Missing libxcb dep |
| awscli | `recipes/a/awscli.toml` | pip install fails |
| neovim | `recipes/n/neovim.toml` | CMake dep downloads fail in sandbox |
| mise | `recipes/m/mise.toml` | Missing openssl build dep |

## Pre-existing SHA256 Mismatches

Source tarballs changed upstream. Update the sha256
in `[source]`.

| Recipe | File |
|--------|------|
| traceroute | `recipes/t/traceroute.toml` |
| libtool | `recipes/l/libtool.toml` |

## Priority Order

1. **Gale bugs** (helix env, helm symlink) — unblock
   recipes, small targeted fixes with TDD
2. **zlib/ncurses deps** — bulk fix, just add deps
   to recipe TOML files, rebuild to verify
3. **Python/pip deps** — similar bulk fix
4. **SHA256 mismatches** — update hashes
5. **Darwin-only recipe fixes** — individual
   investigation per recipe
6. **Source/build issues** — individual investigation
