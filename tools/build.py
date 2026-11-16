#!/usr/bin/env python3
"""Build the upstream static ARM64 daemon and an installable root module."""

import hashlib
from pathlib import Path
import shutil
import subprocess
import tarfile
import zipfile

ROOT = Path(__file__).resolve().parent.parent
BUILD = ROOT / ".agent/.codex/build"
VERSION = "1.16.2"
SHA256 = "2c607f573c6e38815433af289d364a689a203b18b51125f06c4472014d0657f0"
SOURCE_URL = f"https://codeload.github.com/zerotier/ZeroTierOne/tar.gz/refs/tags/{VERSION}"
IMAGE = "zerotier-native-builder"


def run(*args):
    subprocess.run(args, check=True, cwd=ROOT)


def main():
    BUILD.mkdir(parents=True, exist_ok=True)
    archive = BUILD / "zerotier.tar.gz"
    if not archive.exists():
        run("curl", "-fL", "--retry", "2", SOURCE_URL, "-o", str(archive))
    if hashlib.sha256(archive.read_bytes()).hexdigest() != SHA256:
        raise SystemExit(f"Source checksum mismatch: remove {archive} and retry.")
    source = BUILD / f"ZeroTierOne-{VERSION}"
    if not source.exists():
        with tarfile.open(archive) as bundle:
            # This is a pinned, checksum-verified upstream source archive.
            bundle.extractall(BUILD)

    run("docker", "build", "--platform", "linux/arm64", "-t", IMAGE, "-f", "tools/Dockerfile", "tools")
    run("docker", "run", "--rm", "--platform", "linux/arm64",
        "-v", f"{source}:/src", "-w", "/src", IMAGE,
        "make", "-j4", "ZT_STATIC=1", "ZT_SSO_SUPPORTED=0", "ZT_NONFREE=0", "ZT_CONTROLLER=0", "one")
    run("docker", "run", "--rm", "-v", f"{source}:/src", IMAGE, "strip", "/src/zerotier-one")

    stage = BUILD / "module"
    if stage.exists():
        shutil.rmtree(stage)
    shutil.copytree(ROOT / "module", stage)
    (stage / "bin").mkdir()
    shutil.copy2(source / "zerotier-one", stage / "bin/zerotier-one")
    licenses = stage / "licenses"
    licenses.mkdir()
    shutil.copy2(ROOT / "LICENSE", licenses / "module.txt")
    shutil.copy2(source / "LICENSE-MPL.txt", licenses / "ZeroTier-MPL-2.0.txt")
    # Retain bundled dependency notices as well as the daemon's MPL notice.
    for directory in (source / "ext").rglob("*"):
        if directory.is_file() and directory.name.lower().startswith(("license", "copying", "copyright")):
            dest = licenses / "ext" / directory.relative_to(source / "ext")
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(directory, dest)
    (stage / "NOTICE.txt").write_text(
        f"ZeroTier One {VERSION}, built from unmodified upstream source.\n"
        f"Source code: {SOURCE_URL}\nSHA-256: {SHA256}\n"
        "Build: Alpine musl, static ARM64, without SSO or the nonfree controller.\n"
        "Module scripts: MIT. ZeroTier: MPL-2.0. See licenses/ for dependency notices.\n"
    )

    properties = dict(line.split("=", 1) for line in (ROOT / "module/module.prop").read_text().splitlines() if "=" in line)
    output = ROOT / "dist" / f"zerotier-native-{properties['version']}-arm64.zip"
    output.parent.mkdir(exist_ok=True)
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as bundle:
        for path in sorted(stage.rglob("*")):
            if not path.is_file():
                continue
            rel = path.relative_to(stage)
            info = zipfile.ZipInfo(str(rel), (2026, 1, 1, 0, 0, 0))
            executable = path.name.endswith(".sh") or rel.parts[0] == "bin" or rel.parent == Path("system/bin") or path.name == "update-binary"
            mode = 0o755 if executable else 0o644
            info.external_attr = (0o100000 | mode) << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            bundle.writestr(info, path.read_bytes())
    print(f"Built {output} ({output.stat().st_size / 1024 / 1024:.1f} MiB)")


if __name__ == "__main__":
    main()
