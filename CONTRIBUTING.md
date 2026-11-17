# Contributing

English | [简体中文](CONTRIBUTING.zh-CN.md)

Report problems through Issues or submit a Pull Request.

For bug reports, include your Android version, device architecture, root manager and its version, steps to reproduce, and relevant error output. Service logs are in `/data/adb/zerotier-native/service.log`. Keep `identity.secret`, `authtoken.secret`, and other credentials private.

## Building and testing locally

Use ARM64 Linux or Apple Silicon macOS. You need Python 3, curl, Docker, and ShellCheck 0.11.0. Start Docker before building.

```sh
./build.sh
tests/run.sh
```

The build script downloads and verifies the upstream source, then produces a static ARM64 daemon and a module ZIP. Temporary files and build caches are stored in `.agent/.codex/build/`; packages are written to `dist/`. Downloads use the standard `HTTP_PROXY` and `HTTPS_PROXY` environment variables.

Tests unpack and run the generated ZIP. The container has no external network and receives only the `NET_ADMIN` capability; route changes stay inside its network namespace. After the Linux container tests pass, verify installation, startup after reboot, the standard command entry point, and actual communication on Android.

## Code structure and boundaries

- `module/`: installation, service lifecycle, Android route integration, and the `zerotier-cli` entry point.
- `adapter/`: registers ZeroTier interfaces with Android's network management service.
- `tools/`: upstream builds, license collection, and module packaging.
- `tests/`: ShellCheck and integration tests in an isolated network environment.
- `.github/workflows/`: continuous integration and releases.

ZeroTier owns TAP interfaces, addresses, and routes in the `main` table. The module listens for kernel events and uses upstream `devicemap` entries to apply the installer-selected `ethzt` prefix or upstream default naming to joined networks. It mirrors ZeroTier interface routes into table `19993`, marks its routes with protocol `199`, and uses IPv4 and IPv6 `iif lo` rules at priority `19500` for locally originated traffic.

`service.sh` manages startup, shutdown, and crash recovery for the daemon and framework adapter. The framework adapter registers each configured ZeroTier interface as Ethernet through `NetworkAgent`. Addresses, MTU, and routes come from system snapshots updated on kernel events; registration is withdrawn when an interface goes down or disappears. These networks have no internet capability, preserving the existing default network.

Preserve the priority of system VPN and explicit network-selection rules. Check ownership before changing routes; stop and uninstall operations remove only module-owned state. Keep node identity and network data outside the module installation directory and preserve them across upgrades and uninstallations.

KernelSU exposes the command through its existing Root PATH tools directory; Magisk and APatch use systemless mounts. Preserve upstream `zerotier-cli` commands and arguments. Keep the upstream ZeroTier source unchanged and place Android integration in the module.

Shell messages use `zerotier_message` in `module/lib.sh`, with English and Chinese formats and separate format arguments. Language selection reads `persist.sys.locale`, then `ro.product.locale`; Chinese locales select Chinese and all others select English. Keep upstream command output and diagnostic identifiers unchanged. Update both language editions when changing documentation.

The README covers installation, usage, upgrades, uninstallation, and practical limitations. Build, test, architecture, and maintenance instructions belong in this guide. Keep development progress and validation logs out of user documentation.

## Submitting changes

Run checks relevant to your change before submitting. Describe the problem, resulting behavior, and validation method. Split independent changes into separate commits.

Use `type: description` commit messages, for example `fix: preserve foreign routing rules`. Contributed module code uses the MIT license; upstream and third-party code retain their original licenses.

## Releasing a version

Update `version` and increment `versionCode` in `module/module.prop`, then commit and push to `main`. Create an annotated version tag with user-facing release notes:

```sh
version=$(sed -n 's/^version=//p' module/module.prop)
git tag -a "v$version" -m 'Describe the changes for users'
git push origin "v$version"
```

CI checks that the tag matches the module version, builds and tests on an ARM64 runner, then creates a GitHub Release with the tag notes and the installation package. Pushes to `main` and Pull Requests run builds and tests; packages are available in the corresponding Actions run's artifacts.
