"""Run inside a disposable Linux container with CAP_NET_ADMIN and no uplink."""

from pathlib import Path
import io
import os
import json
import shutil
import signal
import subprocess
import time
import unittest
import zipfile

MODULE = Path("/data/adb/modules/zerotier-native")
HOME = Path("/data/adb/zerotier-native")


def command(*args, check=True):
    return subprocess.run(args, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=check, timeout=20)


def ip(*args, check=True):
    return command("/sbin/ip", *args, check=check).stdout


def eventually(predicate, timeout=10):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if predicate():
            return
        time.sleep(0.05)
    raise AssertionError("Condition was not met before timeout")


def cli(*args):
    return command("zerotier-cli", *args, check=False)


def service(*args):
    return command("/bin/busybox", "sh", str(MODULE / "control.sh"), *args, check=False)


def setup_module():
    MODULE.parent.mkdir(parents=True, exist_ok=True)
    properties = dict(line.split("=", 1) for line in Path("/work/module/module.prop").read_text().splitlines() if "=" in line)
    with zipfile.ZipFile(f"/work/dist/zerotier-native-android-{properties['version']}-arm64.zip") as package:
        assert "NOTICE.txt" not in package.namelist()
        assert not any(name.startswith("licenses/") for name in package.namelist())
        assert "LICENSE" not in package.namelist()
        with zipfile.ZipFile(io.BytesIO(package.read("bin/network.jar"))) as adapter:
            assert "classes.dex" in adapter.namelist()
        for source in Path("/work/module").rglob("*"):
            if source.is_file():
                assert package.read(str(source.relative_to("/work/module"))) == source.read_bytes(), "Rebuild the module before testing"
        for entry in package.infolist():
            dest = Path(package.extract(entry, MODULE))
            dest.chmod((entry.external_attr >> 16) & 0o777)
    for name, target in (("/system/bin/ip", "/sbin/ip"), ("/system/bin/sh", "/bin/busybox"),
                         ("/data/adb/magisk/busybox", "/bin/busybox")):
        path = Path(name)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.symlink_to(target)
    # Emulate the root manager's systemless exposure in this container only.
    shutil.copy2(MODULE / "system/bin/zerotier-cli", "/system/bin/zerotier-cli")
    os.environ["PATH"] = "/system/bin:" + os.environ["PATH"]
    # Android framework registration is checked on the phone. Emulate only the
    # app_process lifetime here so the real module supervisor can be exercised.
    app_process = Path("/system/bin/app_process")
    app_process.write_text('#!/bin/sh\n[ -r "$CLASSPATH" ] || exit 1\n'
                           'echo "$$" > /data/adb/zerotier-native/run/android-test.pid\n'
                           'exec sleep 3600\n')
    app_process.chmod(0o755)
    Path("/dev/net").mkdir(exist_ok=True)
    if not Path("/dev/net/tun").exists():
        os.mknod("/dev/net/tun", 0o20600, os.makedev(10, 200))


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.supervisor = subprocess.Popen(["sleep", "3600"])
        self.log = open("/tmp/adapter.log", "w+")
        self.adapter = None
        ip("link", "add", "ztabc12345", "type", "dummy")
        ip("link", "set", "ztabc12345", "up")
        ip("addr", "add", "10.147.17.5/24", "dev", "ztabc12345")
        ip("-6", "addr", "add", "fd00:147:17::5/64", "dev", "ztabc12345", "nodad")
        ip("link", "add", "wlan0", "type", "dummy")
        ip("link", "set", "wlan0", "up")
        ip("addr", "add", "192.0.2.2/24", "dev", "wlan0")
        ip("route", "add", "default", "dev", "wlan0", "table", "1001")
        ip("rule", "add", "pref", "31000", "lookup", "1001")

    def tearDown(self):
        if self.adapter and self.adapter.poll() is None:
            self.adapter.terminate()
            try:
                self.adapter.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.adapter.kill()
                raise
        self.supervisor.terminate()
        self.supervisor.wait()
        if self._outcome.result and (self._outcome.result.failures or self._outcome.result.errors):
            self.log.seek(0)
            print(self.log.read(), flush=True)
        self.log.close()
        for family in ("-4", "-6"):
            ip(family, "rule", "del", "pref", "19500", check=False)
            ip(family, "route", "flush", "table", "19993", check=False)
        ip("rule", "del", "pref", "31000")
        ip("link", "del", "ztabc12345", check=False)
        ip("link", "del", "ztdef12345", check=False)
        ip("link", "del", "wlan0")

    def start_adapter(self):
        self.adapter = subprocess.Popen(
            ["/bin/busybox", "sh", str(MODULE / "routes.sh"), str(self.supervisor.pid)],
            stdout=self.log, stderr=self.log)
        eventually(lambda: "lookup 19993" in ip("rule", "show"))
        eventually(lambda: "lookup 19993" in ip("-6", "rule", "show"))

    def routes(self, family="-4"):
        return ip(family, "route", "show", "table", "19993", check=False)

    def test_android_policy_and_managed_routes(self):
        # Android's default-network table wins over main without the adapter.
        self.assertIn("dev wlan0", ip("route", "get", "10.147.17.8"))
        self.start_adapter()
        eventually(lambda: "10.147.17.0/24" in self.routes())
        self.assertIn("dev ztabc12345", ip("route", "get", "10.147.17.8"))
        self.assertIn("dev ztabc12345", ip("-6", "route", "get", "fd00:147:17::8"))
        self.assertIn("dev wlan0", ip("route", "get", "203.0.113.8"))
        self.assertNotIn("wlan0", self.routes())
        ip("route", "add", "10.42.0.0/16", "via", "10.147.17.1", "dev", "ztabc12345")
        eventually(lambda: "10.42.0.0/16 via 10.147.17.1" in self.routes())
        ip("route", "replace", "10.42.0.0/16", "via", "10.147.17.2", "dev", "ztabc12345")
        eventually(lambda: "10.42.0.0/16 via 10.147.17.2" in self.routes())
        ip("route", "del", "10.42.0.0/16")
        eventually(lambda: "10.42.0.0/16" not in self.routes())

    def test_start_with_managed_gateway_routes(self):
        ip("route", "add", "10.0.0.0/8", "via", "10.147.17.1", "dev", "ztabc12345")
        ip("-6", "route", "add", "fd00::/16", "via", "fd00:147:17::1", "dev", "ztabc12345")
        self.start_adapter()
        eventually(lambda: "10.0.0.0/8 via 10.147.17.1" in self.routes())
        eventually(lambda: "fd00::/16 via fd00:147:17::1" in self.routes("-6"))

    def test_stop_cleans_only_owned_state(self):
        self.start_adapter()
        self.adapter.terminate()
        self.adapter.wait(timeout=10)
        self.assertEqual("", self.routes())
        self.assertEqual("", self.routes("-6"))
        self.assertNotIn("19500:", ip("rule", "show"))
        self.assertIn("10.147.17.0/24", ip("route", "show", "table", "main"))
        self.assertIn("lookup 1001", ip("rule", "show"))
        self.assertIn("default dev wlan0", ip("route", "show", "table", "1001"))

    def test_network_join_leave_bursts(self):
        self.start_adapter()
        for _ in range(10):
            ip("link", "add", "ztdef12345", "type", "dummy")
            ip("link", "set", "ztdef12345", "up")
            ip("addr", "add", "10.148.17.5/24", "dev", "ztdef12345")
            ip("route", "add", "10.42.0.0/16", "via", "10.148.17.1", "dev", "ztdef12345")
            ip("link", "del", "ztdef12345")
        ip("link", "add", "ztdef12345", "type", "dummy")
        ip("link", "set", "ztdef12345", "up")
        ip("addr", "add", "10.148.17.5/24", "dev", "ztdef12345")
        ip("route", "add", "10.42.0.0/16", "via", "10.148.17.1", "dev", "ztdef12345")
        eventually(lambda: "10.42.0.0/16 via 10.148.17.1" in self.routes())
        ip("link", "del", "ztdef12345")
        eventually(lambda: "ztdef12345" not in self.routes())
        self.assertIsNone(self.adapter.poll())
        self.assertIn("dev ztabc12345", ip("route", "get", "10.147.17.8"))

    def test_link_down_and_up_preserves_the_adapter(self):
        ip("route", "add", "10.42.0.0/16", "via", "10.147.17.1", "dev", "ztabc12345")
        self.start_adapter()
        eventually(lambda: "10.42.0.0/16" in self.routes())
        ip("link", "set", "ztabc12345", "down")
        eventually(lambda: "10.42.0.0/16" not in self.routes())
        time.sleep(1.2)
        self.assertIsNone(self.adapter.poll())
        ip("link", "set", "ztabc12345", "up")
        eventually(lambda: "10.147.17.0/24" in self.routes())
        # The upstream daemon restores managed routes in main after link-up.
        ip("route", "replace", "10.42.0.0/16", "via", "10.147.17.1", "dev", "ztabc12345")
        eventually(lambda: "10.42.0.0/16" in self.routes())

    def test_persistent_route_apply_failure_stops_the_adapter(self):
        path = Path("/system/bin/ip")
        path.unlink()
        path.write_text('''#!/bin/sh
case "$*" in
    "-4 route append "*) echo 'route apply failed' >&2; exit 2 ;;
    *) exec /sbin/ip "$@" ;;
esac
''')
        path.chmod(0o755)
        try:
            self.adapter = subprocess.Popen(
                ["/bin/busybox", "sh", str(MODULE / "routes.sh"), str(self.supervisor.pid)],
                stdout=self.log, stderr=self.log)
            self.assertNotEqual(0, self.adapter.wait(timeout=10))
            self.log.seek(0)
            self.assertIn("route apply failed", self.log.read())
        finally:
            path.unlink()
            path.symlink_to("/sbin/ip")

    def test_rule_and_table_recovery_and_network_switch(self):
        self.start_adapter()
        ip("rule", "del", "pref", "19500")
        eventually(lambda: "19500:" in ip("rule", "show"))
        ip("route", "flush", "table", "19993")
        eventually(lambda: "10.147.17.0/24" in self.routes())
        ip("-6", "rule", "del", "pref", "19500")
        eventually(lambda: "19500:" in ip("-6", "rule", "show"))
        ip("link", "set", "wlan0", "down")
        ip("link", "set", "wlan0", "up")
        eventually(lambda: "dev ztabc12345" in ip("route", "get", "10.147.17.8"))
        ip("link", "del", "ztabc12345")
        eventually(lambda: "ztabc12345" not in self.routes() and "ztabc12345" not in self.routes("-6"))

    def test_multiple_networks_linklocal_routes_and_idle(self):
        ip("link", "add", "ztdef12345", "type", "dummy")
        ip("link", "set", "ztdef12345", "up")
        ip("addr", "add", "10.148.17.5/24", "dev", "ztdef12345")
        ip("-6", "addr", "add", "fd00:148:17::5/64", "dev", "ztdef12345", "nodad")
        self.start_adapter()
        eventually(lambda: "10.148.17.0/24" in self.routes())
        eventually(lambda: self.routes("-6").count("fe80::/64") == 2)
        time.sleep(0.5)
        before = Path(f"/proc/{self.adapter.pid}/stat").read_text().split()
        before_children = Path(f"/proc/{self.adapter.pid}/task/{self.adapter.pid}/children").read_text()
        time.sleep(0.5)
        after = Path(f"/proc/{self.adapter.pid}/stat").read_text().split()
        self.assertEqual(before[13:17], after[13:17], "Adapter must sleep when routes are unchanged")
        self.assertEqual(before_children, Path(f"/proc/{self.adapter.pid}/task/{self.adapter.pid}/children").read_text())
        self.assertIsNone(self.adapter.poll())

    def test_conflicting_rule_is_preserved(self):
        ip("rule", "add", "pref", "19500", "lookup", "1001")
        self.adapter = subprocess.Popen(
            ["/bin/busybox", "sh", str(MODULE / "routes.sh"), str(self.supervisor.pid)],
            stdout=self.log, stderr=self.log)
        self.assertNotEqual(self.adapter.wait(timeout=10), 0)
        self.assertIn("19500:", ip("rule", "show"))
        self.assertIn("lookup 1001", ip("rule", "show"))

    def test_android_rule_whitespace_does_not_create_a_conflict(self):
        path = Path("/system/bin/ip")
        path.unlink()
        path.write_text('''#!/bin/sh
case "$*" in
    "-4 rule show"|"-6 rule show") /sbin/ip "$@" | sed 's/$/ /' ;;
    *) exec /sbin/ip "$@" ;;
esac
''')
        path.chmod(0o755)
        try:
            self.start_adapter()
            time.sleep(0.2)
            self.assertIsNone(self.adapter.poll())
            self.adapter.terminate()
            self.adapter.wait(timeout=10)
            self.assertNotIn("19500:", ip("rule", "show"))
            self.assertNotIn("19500:", ip("-6", "rule", "show"))
        finally:
            path.unlink()
            path.symlink_to("/sbin/ip")

    def test_conflicting_table_is_preserved(self):
        ip("route", "add", "203.0.113.0/24", "dev", "wlan0", "table", "19993")
        self.adapter = subprocess.Popen(
            ["/bin/busybox", "sh", str(MODULE / "routes.sh"), str(self.supervisor.pid)],
            stdout=self.log, stderr=self.log)
        self.assertNotEqual(self.adapter.wait(timeout=10), 0)
        self.assertIn("203.0.113.0/24", self.routes())

    def test_conflicting_rule_with_extra_selector_is_preserved(self):
        ip("rule", "add", "pref", "19500", "iif", "lo", "uidrange", "12345-12345", "lookup", "19993")
        self.adapter = subprocess.Popen(
            ["/bin/busybox", "sh", str(MODULE / "routes.sh"), str(self.supervisor.pid)],
            stdout=self.log, stderr=self.log)
        self.assertNotEqual(self.adapter.wait(timeout=10), 0)
        self.assertIn("uidrange 12345-12345", ip("rule", "show"))

    def test_vpn_and_explicit_network_rules_keep_precedence(self):
        self.start_adapter()
        ip("rule", "add", "pref", "16000", "fwmark", "0x64", "lookup", "1001")
        try:
            self.assertIn("dev wlan0", ip("route", "get", "10.147.17.8", "mark", "0x64"))
            self.assertIn("dev ztabc12345", ip("route", "get", "10.147.17.8"))
        finally:
            ip("rule", "del", "pref", "16000")
        ip("rule", "add", "pref", "14000", "prohibit")
        try:
            self.assertNotEqual(command("/sbin/ip", "route", "get", "10.147.17.8", check=False).returncode, 0)
        finally:
            ip("rule", "del", "pref", "14000")


class KernelSUCommandTests(unittest.TestCase):
    def setUp(self):
        self.original_path = os.environ["PATH"]
        self.magisk_busybox = Path("/data/adb/magisk/busybox")
        self.magisk_busybox.rename(self.magisk_busybox.with_suffix(".disabled"))
        self.system_cli = Path("/system/bin/zerotier-cli")
        self.system_cli.rename(self.system_cli.with_suffix(".disabled"))
        self.directory = Path("/data/adb/ksu/bin")
        self.directory.mkdir(parents=True, exist_ok=True)
        (self.directory / "busybox").symlink_to("/bin/busybox")
        os.environ["PATH"] += ":" + str(self.directory)

    def tearDown(self):
        service("stop")
        for name in ("busybox", "zerotier-cli"):
            (self.directory / name).unlink(missing_ok=True)
        self.magisk_busybox.with_suffix(".disabled").rename(self.magisk_busybox)
        self.system_cli.with_suffix(".disabled").rename(self.system_cli)
        os.environ["PATH"] = self.original_path

    def test_native_cli_without_a_system_mount_and_uninstall_cleanup(self):
        service("start")
        eventually(lambda: (self.directory / "zerotier-cli").exists() and cli("status").returncode == 0, timeout=20)
        self.assertEqual(str(self.directory / "zerotier-cli"), shutil.which("zerotier-cli"))
        self.assertIn("1.16.2", cli("-v").stdout)
        result = command("/bin/busybox", "sh", str(MODULE / "uninstall.sh"), check=False)
        self.assertEqual(0, result.returncode)
        self.assertFalse((self.directory / "zerotier-cli").exists())
        self.assertTrue((HOME / "identity.secret").exists())

    def test_existing_command_is_preserved(self):
        existing = self.directory / "zerotier-cli"
        existing.write_text("another installation")
        service("start")
        eventually(lambda: (HOME / "service.log").exists() and "belongs to another installation" in (HOME / "service.log").read_text())
        self.assertEqual("another installation", existing.read_text())
        command("/bin/busybox", "sh", str(MODULE / "uninstall.sh"))
        self.assertEqual("another installation", existing.read_text())


class SupervisorTests(unittest.TestCase):
    def tearDown(self):
        service("stop")

    def test_daemon_cli_restart_singleton_and_cleanup(self):
        service("start")
        eventually(lambda: cli("status").returncode == 0, timeout=20)
        first = (HOME / "run/service.pid").read_text()
        daemon = (HOME / "zerotier-one.pid").read_text()
        service("start")
        time.sleep(0.2)
        self.assertEqual(first, (HOME / "run/service.pid").read_text())
        self.assertEqual(daemon, (HOME / "zerotier-one.pid").read_text())
        os.kill(int(daemon), signal.SIGKILL)
        eventually(lambda: (HOME / "zerotier-one.pid").read_text() != daemon, timeout=15)
        eventually(lambda: cli("status").returncode == 0)
        identity = (HOME / "identity.secret").read_bytes()
        self.assertEqual(0, service("stop").returncode)
        self.assertNotEqual(0, cli("status").returncode)
        self.assertFalse((HOME / "run/service.pid").exists())
        self.assertNotIn("19500:", ip("rule", "show"))
        self.assertNotIn("19500:", ip("-6", "rule", "show"))
        self.assertEqual(identity, (HOME / "identity.secret").read_bytes())
        self.assertEqual(0o700, HOME.stat().st_mode & 0o777)
        self.assertEqual(0o600, (HOME / "identity.secret").stat().st_mode & 0o777)
        self.assertFalse(any("/zerotier-native/routes.sh" in p.read_text(errors="replace")
                             for p in Path("/proc").glob("[0-9]*/cmdline") if p.exists()))
        self.assertFalse(any("/zerotier-native/network.sh" in p.read_text(errors="replace")
                             for p in Path("/proc").glob("[0-9]*/cmdline") if p.exists()))

    def test_network_registration_process_restarts_and_stops(self):
        pidfile = HOME / "run/android-test.pid"
        pidfile.unlink(missing_ok=True)
        service("start")
        eventually(pidfile.exists)
        first = pidfile.read_text()
        os.kill(int(first), signal.SIGKILL)
        eventually(lambda: pidfile.read_text() != first, timeout=12)
        current = pidfile.read_text().strip()
        self.assertEqual(0, service("stop").returncode)
        self.assertFalse(Path("/proc", current).exists())

    def test_standard_cli_join_status_json_and_leave(self):
        self.assertEqual("/system/bin/zerotier-cli", shutil.which("zerotier-cli"))
        self.assertFalse((MODULE / "zerotier-native").exists())
        service("start")
        eventually(lambda: cli("status").returncode == 0, timeout=20)
        self.assertIn("join", cli("-h").stdout)
        self.assertIn("address", json.loads(cli("-j", "status").stdout))
        network = "0123456789abcdef"
        self.assertEqual(0, cli("join", network).returncode)
        networks = json.loads(cli("-j", "listnetworks").stdout)
        self.assertTrue(any(n["nwid"] == network for n in networks))
        self.assertTrue((HOME / "networks.d" / (network + ".conf")).exists())
        self.assertEqual(0, cli("leave", network).returncode)
        self.assertFalse((HOME / "networks.d" / (network + ".conf")).exists())


class InstallerTests(unittest.TestCase):
    def install(self, arch):
        script = r'''
            abort() { echo "$*" >&2; exit 1; }
            ui_print() { echo "$*"; }
            set_perm() { chown "$2:$3" "$1"; chmod "$4" "$1"; }
            set_perm_recursive() {
                chown -R "$2:$3" "$1"
                find "$1" -type d -exec chmod "$4" '{}' +
                find "$1" -type f -exec chmod "$5" '{}' +
            }
            . "$MODPATH/customize.sh"
        '''
        return subprocess.run(["/bin/busybox", "sh", "-c", script],
                              env=dict(os.environ, BOOTMODE="true", ARCH=arch, API="36", MODPATH=str(MODULE)),
                              capture_output=True, text=True, timeout=20)

    def test_install_permissions_and_data_preservation(self):
        # KernelSU's unzip does not preserve the ZIP executable mode.
        for path in MODULE.rglob("*"):
            if path.is_file():
                path.chmod(0o644)
        HOME.mkdir(exist_ok=True)
        config = HOME / "local.conf"
        config.write_text('{"settings": {}}')
        result = self.install("arm64")
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual('{"settings": {}}', config.read_text())
        self.assertEqual(0o700, HOME.stat().st_mode & 0o777)
        for executable in ("service.sh", "routes.sh", "network.sh", "control.sh", "uninstall.sh", "bin/zerotier-one", "system/bin/zerotier-cli"):
            self.assertEqual(0o755, (MODULE / executable).stat().st_mode & 0o777)
        self.assertFalse((MODULE / "skip_mount").exists())
        self.assertEqual("#MAGISK", (MODULE / "META-INF/com/google/android/updater-script").read_text().strip())

    def test_unsupported_architecture_is_rejected(self):
        result = self.install("x86")
        self.assertNotEqual(0, result.returncode)
        self.assertIn("ARM64", result.stderr)


if __name__ == "__main__":
    setup_module()
    unittest.main(verbosity=2)
