#!/system/bin/sh

[ "$BOOTMODE" = true ] || abort 'Unsupported installation mode.'
[ "$ARCH" = arm64 ] || abort 'This package requires an ARM64 device.'
[ "$API" -ge 30 ] || abort 'Android 11 or later is required.'
[ -c /dev/net/tun ] || [ -c /dev/tun ] || abort 'The device kernel must provide TUN/TAP.'
[ -x /system/bin/ip ] || abort '/system/bin/ip is required.'

# Root-manager unzip may create every payload file with mode 0644.
set_perm_recursive "$MODPATH" 0 0 0755 0644
for script in service.sh routes.sh uninstall.sh; do
    set_perm "$MODPATH/$script" 0 0 0755
done
set_perm "$MODPATH/bin/zerotier-one" 0 0 0755
set_perm "$MODPATH/system/bin/zerotier-cli" 0 0 0755
"$MODPATH/bin/zerotier-one" -v || abort 'The ZeroTier binary cannot run on this device.'

# Validate the replacement before stopping a working installation.
OLDMOD=/data/adb/modules/zerotier-native
if [ -f "$OLDMOD/service.sh" ]; then
    (
        MODDIR=$OLDMOD
        # shellcheck source=module/lib.sh
        . "$MODPATH/lib.sh"
        zerotier_init
        zerotier_stop
    ) || abort 'Could not stop the existing service.'
fi
mkdir -p /data/adb/zerotier-native
set_perm /data/adb/zerotier-native 0 0 0700
ui_print 'Reboot, then join a network:'
ui_print 'zerotier-cli join NETWORK_ID'
