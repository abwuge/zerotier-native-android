#!/system/bin/sh
# shellcheck shell=busybox

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

ui_print '网卡命名：音量＋使用 ethzt 前缀（默认，8 秒超时）'
ui_print '音量－使用 ZeroTier 默认命名'
(
    MODDIR=$MODPATH
    # shellcheck source=module/lib.sh
    . "$MODPATH/lib.sh"
    zerotier_init
    interface_naming=ethernet
    key_events=$MODPATH/.volume-key-events
    key_reader_pid=
    # shellcheck disable=SC2329
    cleanup_key_reader() {
        [ -z "$key_reader_pid" ] || kill "$key_reader_pid" 2>/dev/null
        [ -z "$key_reader_pid" ] || wait "$key_reader_pid" 2>/dev/null
        rm -f "$key_events"
    }
    trap cleanup_key_reader EXIT
    mkfifo "$key_events" || exit 1
    exec 7<>"$key_events"
    /system/bin/getevent -ql >&7 2>/dev/null &
    key_reader_pid=$!
    deadline=$(( $(date +%s) + 8 ))
    while :; do
        remaining=$(( deadline - $(date +%s) ))
        [ "$remaining" -gt 0 ] || break
        # Timed reads are provided by the installer's BusyBox ash.
        # shellcheck disable=SC3045
        IFS= read -r -t "$remaining" key_event <&7 || break
        case "$key_event" in
            *KEY_VOLUMEUP*DOWN*) break ;;
            *KEY_VOLUMEDOWN*DOWN*) interface_naming=default; break ;;
        esac
    done
    printf '%s\n' "$interface_naming" > "$MODPATH/interface-naming"
) || abort 'Could not select interface naming.'
read -r interface_naming < "$MODPATH/interface-naming"
case "$interface_naming" in
    ethernet) ui_print '已选择 ethzt 前缀命名' ;;
    default) ui_print '已选择 ZeroTier 默认命名' ;;
esac

mkdir -p /data/adb/zerotier-native
set_perm /data/adb/zerotier-native 0 0 0700
ui_print 'Reboot, then join a network:'
ui_print 'zerotier-cli join NETWORK_ID'
