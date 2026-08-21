"""Darwin/arm64 admit inputs for the first-ten heading.

Argv only. gale admit on a Darwin host still has to
print tree_digest. Do not invent hashes here.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Package:
    name: str
    version: str
    description: str
    license: str
    homepage: str
    repo: str
    url: str
    format: str
    strip: int
    hash_source: str
    sha256: str
    files: tuple[str, ...]


PACKAGES: tuple[Package, ...] = (
    Package(
        name="jq",
        version="1.8.2",
        description="Lightweight and flexible command-line JSON processor",
        license="MIT",
        homepage="https://jqlang.github.io/jq",
        repo="jqlang/jq",
        url="https://github.com/jqlang/jq/releases/download/jq-1.8.2/jq-macos-arm64",
        format="binary",
        strip=0,
        hash_source="upstream-sha256sums",
        sha256="2d75340ba57a4b4b4c8708a21c2dc8e958a48aaa8bba13b27f77f6e4c0eca07e",
        files=("jq-macos-arm64:bin/jq:755",),
    ),
    Package(
        name="ripgrep",
        version="15.2.0",
        description="Search tool like grep and The Silver Searcher",
        license="Unlicense",
        homepage="https://github.com/BurntSushi/ripgrep",
        repo="BurntSushi/ripgrep",
        url="https://github.com/BurntSushi/ripgrep/releases/download/15.2.0/ripgrep-15.2.0-aarch64-apple-darwin.tar.gz",
        format="tar.gz",
        strip=1,
        hash_source="upstream-sha256sums",
        sha256="3750b2e93f37e0c692657da574d7019a101c0084da05a790c83fd335bad973e4",
        files=("rg:bin/rg:755",),
    ),
    Package(
        name="fd",
        version="10.4.2",
        description="Simple, fast and user-friendly alternative to find",
        license="Apache-2.0",
        homepage="https://github.com/sharkdp/fd",
        repo="sharkdp/fd",
        url="https://github.com/sharkdp/fd/releases/download/v10.4.2/fd-v10.4.2-aarch64-apple-darwin.tar.gz",
        format="tar.gz",
        strip=1,
        hash_source="computed",
        sha256="",
        files=("fd:bin/fd:755",),
    ),
    Package(
        name="just",
        version="1.58.0",
        description="Handy way to save and run project-specific commands",
        license="CC0-1.0",
        homepage="https://github.com/casey/just",
        repo="casey/just",
        url="https://github.com/casey/just/releases/download/1.58.0/just-1.58.0-aarch64-apple-darwin.tar.gz",
        format="tar.gz",
        strip=0,
        hash_source="upstream-sha256sums",
        sha256="50ae3e996c974a0bf32ea7d10f495070df33f1b43e0616b2769e3d4821ed8f48",
        files=("just:bin/just:755",),
    ),
    Package(
        name="gh",
        version="2.98.0",
        description="GitHub command-line tool",
        license="MIT",
        homepage="https://cli.github.com/",
        repo="cli/cli",
        url="https://github.com/cli/cli/releases/download/v2.98.0/gh_2.98.0_macOS_arm64.zip",
        format="zip",
        strip=1,
        hash_source="upstream-sha256sums",
        sha256="8cfb027cc5310675f2b830eac8f9865c1155a45ffcf9757f699fdd5a22046ca4",
        files=("bin/gh:bin/gh:755",),
    ),
    Package(
        name="direnv",
        version="2.37.1",
        description="Per-directory environment variables",
        license="MIT",
        homepage="https://direnv.net",
        repo="direnv/direnv",
        url="https://github.com/direnv/direnv/releases/download/v2.37.1/direnv.darwin-arm64",
        format="binary",
        strip=0,
        hash_source="computed",
        sha256="",
        files=("direnv.darwin-arm64:bin/direnv:755",),
    ),
    Package(
        name="gofumpt",
        version="0.11.0",
        description="Stricter gofmt",
        license="BSD-3-Clause",
        homepage="https://github.com/mvdan/gofumpt",
        repo="mvdan/gofumpt",
        url="https://github.com/mvdan/gofumpt/releases/download/v0.11.0/gofumpt_v0.11.0_darwin_arm64",
        format="binary",
        strip=0,
        hash_source="computed",
        sha256="",
        files=("gofumpt_v0.11.0_darwin_arm64:bin/gofumpt:755",),
    ),
    Package(
        name="golangci-lint",
        version="2.13.1",
        description="Fast Go linters runner",
        license="GPL-3.0",
        homepage="https://golangci-lint.run",
        repo="golangci/golangci-lint",
        url="https://github.com/golangci/golangci-lint/releases/download/v2.13.1/golangci-lint-2.13.1-darwin-arm64.tar.gz",
        format="tar.gz",
        strip=1,
        hash_source="upstream-sha256sums",
        sha256="0c9818baf6fb8ad26c6d2ef51b68d5a1e260ef07727036b1431647cc44637c7c",
        files=("golangci-lint:bin/golangci-lint:755",),
    ),
)


def by_name(name: str) -> Package:
    for p in PACKAGES:
        if p.name == name:
            return p
    raise KeyError(name)


def admit_argv(pkg: Package, archive: str) -> list[str]:
    argv = [
        "gale", "admit",
        "--archive", archive,
        "--name", pkg.name,
        "--version", pkg.version,
        "--os", "darwin",
        "--arch", "arm64",
        "--url", pkg.url,
        "--format", pkg.format,
        "--strip", str(pkg.strip),
        "--hash-source", pkg.hash_source,
    ]
    if pkg.hash_source == "upstream-sha256sums":
        argv.extend(["--sha256", pkg.sha256])
    for fe in pkg.files:
        argv.extend(["--file", fe])
    return argv


def header(pkg: Package) -> str:
    return (
        f"[package]\n"
        f'name = "{pkg.name}"\n'
        f'description = "{pkg.description}"\n'
        f'license = "{pkg.license}"\n'
        f'homepage = "{pkg.homepage}"\n'
        f'repo = "{pkg.repo}"\n'
        f'latest = "{pkg.version}"\n'
    )
