# Upstream Tracking

The build-status dashboard shows, for every recipe,
whether upstream has shipped a newer version and how
long ago that release dropped. Data lives in
`_data/upstream.json`, rewritten daily by
`.github/workflows/auto-update.yml`.

## Data shape

```json
{
  "generated_at": "2026-04-18T09:17:00Z",
  "recipes": {
    "<name>": {
      "status":              "up_to_date|outdated|untracked|error",
      "current_version":     "<recipe version at check time>",
      "checked_at":          "<ISO 8601 UTC>",

      "latest_version":      "<upstream tag, normalized>",
      "latest_released_at":  "<YYYY-MM-DD>",
      "latest_release_url":  "<URL>",
      "reason":              "<why untracked, if applicable>"
    }
  }
}
```

`latest_*` fields are present for `up_to_date` and
`outdated`. `reason` is present for `untracked` / `error`.

## How checks run

`auto-update.sh` walks every recipe under `recipes/*/*.toml`:

- If `source.repo` is missing → `untracked`, reason
  noted.
- Otherwise → GET `/repos/{repo}/releases/latest`. If
  the release endpoint 404s, fall back to
  `/repos/{repo}/tags?per_page=100` and pick the highest
  semver-shaped tag (covers upstreams that publish tags
  without releases: git/git, golang/go, python/cpython,
  etc.). Either way, strip prefixes to recover the
  underlying version string: recipe-name prefix
  (`git-delta-`), monorepo sub-tag (`gopls/`), generic
  project prefix (`llvmorg-`, `openssl-`, `bun-`), and
  leading `v`. Compare to `package.version`. Equal → `up_to_date`.
  Different → `outdated` (dashboard shows this
  immediately; auto-PR still gates on the 7-day
  first-observation cooldown).
- API 404 or network error on both endpoints →
  `untracked`, reason noted.
- `source_type` (`"release"` or `"tag"`) is recorded on
  every entry so reviewers can see which path produced
  the observation.

Calls are paced at 300–900 ms between recipes and the
cron starts at 09:17 UTC with a 0–59 s startup jitter,
to keep us off top-of-hour API spikes.

## Adding a non-GitHub livecheck rule

`auto-update.sh` is the one place to extend. Add a branch
before the `gh api /releases/latest` call that dispatches
on the `source.url` host (e.g. `ftp.gnu.org`,
`sourceforge.net`, `registry.npmjs.org`). Each branch
should populate `new_tag` / `new_version` /
`published_at` the same way the GitHub path does; the
`emit_upstream` call and PR logic downstream don't care
where the data came from.

Keep the parser small and defensive — missing or
unparseable upstream data should fall through to
`untracked` with a clear `reason`, not a hard error.
