"""First-four Darwin/arm64 admit inputs.

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
