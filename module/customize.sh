#!/system/bin/sh

[ "$BOOTMODE" = true ] || abort 'Install from the Magisk, KernelSU, or APatch app.'
[ "$ARCH" = arm64 ] || abort 'This package requires an ARM64 device.'
[ -c /dev/net/tun ] || [ -c /dev/tun ] || abort 'The device kernel must provide TUN/TAP.'
[ -x /system/bin/ip ] || abort '/system/bin/ip is required.'

# Updating must stop the old supervisor before its executable is replaced.
OLDMOD=/data/adb/modules/zerotier-native
if [ -f "$OLDMOD/control.sh" ]; then
    sh "$OLDMOD/control.sh" stop || abort 'Could not stop the existing service.'
fi

"$MODPATH/bin/zerotier-one" -v || abort 'The ZeroTier binary cannot run on this device.'
mkdir -p /data/adb/zerotier-native
set_perm_recursive "$MODPATH" 0 0 0755 0644
for script in service.sh routes.sh control.sh uninstall.sh; do
    set_perm "$MODPATH/$script" 0 0 0755
done
set_perm "$MODPATH/bin/zerotier-one" 0 0 0755
set_perm "$MODPATH/system/bin/zerotier-cli" 0 0 0755
set_perm /data/adb/zerotier-native 0 0 0700
ui_print 'Installed. Reboot, then run as root:'
ui_print 'zerotier-cli join NETWORK_ID'
