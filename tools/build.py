#!/usr/bin/env python3
"""Build the upstream static ARM64 daemon and an installable root module."""

import base64
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
SDK_URL = "https://android.googlesource.com/platform/prebuilts/sdk/+/3af7c93524be6f51e092b87b17f009f13ee98b43/35/module-lib"
ANDROID_TOOLS = {
    "android.jar": (f"{SDK_URL}/android.jar?format=TEXT", "63c41d8dfaa7f2a5c5ba056fad50af829782e4d6f082484ec91a85a0694e752d"),
    "framework-connectivity.jar": (f"{SDK_URL}/framework-connectivity.jar?format=TEXT", "2fc928c1077cd25366edc2da92a1530a2eefdf39c65fe5def0e98f4ea0a19bf0"),
    "framework-connectivity-t.jar": (f"{SDK_URL}/framework-connectivity-t.jar?format=TEXT", "77e6a7a5d2a35d26a8ae0bec9c42e7f6d9376e70598a444b8a576000dcdfecd1"),
    "r8.jar": ("https://dl.google.com/dl/android/maven2/com/android/tools/r8/8.9.35/r8-8.9.35.jar", "204b2fc2b0f4e888dc0ef748b58090def1bf4185068d36abbb94841dbc7107a8"),
}


def run(*args):
    subprocess.run(args, check=True, cwd=ROOT)


def build_network_adapter():
    for name, (url, digest) in ANDROID_TOOLS.items():
        destination = BUILD / name
        if not destination.exists():
            download = BUILD / (name + ".download")
            run("curl", "-fL", "--retry", "2", url, "-o", str(download))
            data = download.read_bytes()
            destination.write_bytes(base64.b64decode(data) if url.endswith("format=TEXT") else data)
            download.unlink()
        if hashlib.sha256(destination.read_bytes()).hexdigest() != digest:
            raise SystemExit(f"Build dependency checksum mismatch: {destination}")
    classes = BUILD / "android/classes"
    dex = BUILD / "android/dex"
    if classes.parent.exists():
        shutil.rmtree(classes.parent)
    classes.mkdir(parents=True)
    dex.mkdir()
    libraries = ["android.jar", "framework-connectivity.jar", "framework-connectivity-t.jar"]
    classpath = ":".join("/work/.agent/.codex/build/" + name for name in libraries)
    run("docker", "run", "--rm", "-v", f"{ROOT}:/work", "-w", "/work", IMAGE,
        "javac", "--release", "11", "-cp", classpath, "-d", "/work/.agent/.codex/build/android/classes",
        "adapter/NetworkAdapter.java")
    library_args = [argument for name in libraries for argument in ("--lib", "/work/.agent/.codex/build/" + name)]
    inputs = ["/work/" + str(path.relative_to(ROOT)) for path in classes.rglob("*.class")]
    run("docker", "run", "--rm", "-v", f"{ROOT}:/work", "-w", "/work", IMAGE,
        "java", "-cp", "/work/.agent/.codex/build/r8.jar", "com.android.tools.r8.D8",
        "--min-api", "30", *library_args, "--output", "/work/.agent/.codex/build/android/dex", *inputs)
    with zipfile.ZipFile(BUILD / "network.jar", "w", zipfile.ZIP_DEFLATED) as package:
        package.write(dex / "classes.dex", "classes.dex")


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
    build_network_adapter()
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
    shutil.copy2(BUILD / "network.jar", stage / "bin/network.jar")
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
    output = ROOT / "dist" / f"zerotier-native-android-{properties['version']}-arm64.zip"
    output.parent.mkdir(exist_ok=True)
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as bundle:
        for path in sorted(stage.rglob("*")):
            if not path.is_file():
                continue
            rel = path.relative_to(stage)
            info = zipfile.ZipInfo(str(rel), (2026, 1, 1, 0, 0, 0))
            executable = path.name.endswith(".sh") or (rel.parts[0] == "bin" and path.suffix != ".jar") or rel.parent == Path("system/bin") or path.name == "update-binary"
            mode = 0o755 if executable else 0o644
            info.external_attr = (0o100000 | mode) << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            bundle.writestr(info, path.read_bytes())
    print(f"Built {output} ({output.stat().st_size / 1024 / 1024:.1f} MiB)")


if __name__ == "__main__":
    main()
