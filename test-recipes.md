# Test Recipes for gale create-recipe

Packages used to test AI recipe generation.

## Round 1 — Build system coverage

| Recipe | Build System | Builds? |
|--------|-------------|---------|
| sd | Rust/cargo | Yes |
| gitui | Rust/cargo | Yes |
| lazydocker | Go | Yes |
| dive | Go | Yes |
| croc | Go | Yes |
| htop | C/autotools | Yes |
| libssh2 | C/cmake | Yes |
| flyctl | Go | Yes |
| nushell | Rust/cargo | Yes |
| lsd | Rust/cargo | Yes |

## Round 2 — New build systems (meson, zig, python, ruby)

| Recipe | Build System | Builds? | Issue |
|--------|-------------|---------|-------|
| libpsl | meson | Yes | |
| inih | meson | No | No meson/ninja recipe |
| zls | zig | No | Existing zig recipe broken |
| zf | zig | No | Existing zig recipe broken |
| httpie | python | No | sqlite recipe build error |
| yt-dlp | python | No | sqlite recipe build error |
| glances | python | No | sqlite recipe build error |
| tmuxinator | ruby | No | libyaml recipe build error |
| cocoapods | ruby | No | libyaml recipe build error |
| colorls | ruby | No | libyaml recipe build error |
