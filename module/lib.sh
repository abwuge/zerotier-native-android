#!/system/bin/sh

ZEROTIER_HOME=/data/adb/zerotier-native
ZEROTIER_RUN=$ZEROTIER_HOME/run

# Android stores the selected system language here; other locales use English.
ZEROTIER_LANGUAGE=$(getprop persist.sys.locale 2>/dev/null)
[ -n "$ZEROTIER_LANGUAGE" ] || ZEROTIER_LANGUAGE=$(getprop ro.product.locale 2>/dev/null)

zerotier_message() {
    case "$ZEROTIER_LANGUAGE" in
        zh|zh-*|zh_*) message=$2 ;;
        *) message=$1 ;;
    esac
    shift 2
    # Formats are module-owned strings; arguments are passed without evaluation.
    # shellcheck disable=SC2059
    printf "$message\n" "$@"
}

zerotier_init() {
    [ "$(id -u)" = 0 ] || { zerotier_message 'Permission denied. Run as root.' '权限不足，请以 root 身份运行。' >&2; exit 1; }
    umask 077
    mkdir -p "$ZEROTIER_RUN"
    chmod 700 "$ZEROTIER_HOME" "$ZEROTIER_RUN"
    for ZEROTIER_BB in /data/adb/magisk/busybox /data/adb/ksu/bin/busybox /data/adb/ap/bin/busybox; do
        [ ! -x "$ZEROTIER_BB" ] || break
    done
    [ -x "$ZEROTIER_BB" ] || { zerotier_message 'BusyBox was not found.' '未找到 BusyBox。' >&2; exit 1; }
    export ASH_STANDALONE=1
}

zerotier_running() {
    [ -r "$ZEROTIER_RUN/service.pid" ] || return 1
    read -r ZEROTIER_PID < "$ZEROTIER_RUN/service.pid"
    case "$ZEROTIER_PID" in ''|*[!0-9]*) return 1 ;; esac
    [ -r "/proc/$ZEROTIER_PID/cmdline" ] || return 1
    "$ZEROTIER_BB" tr '\000' '\n' < "/proc/$ZEROTIER_PID/cmdline" | "$ZEROTIER_BB" grep -Fxq "$MODDIR/service.sh"
}

zerotier_stop() {
    if zerotier_running; then
        stopping_pid=$ZEROTIER_PID
        kill -TERM "$ZEROTIER_PID" || return 1
        # Wait only for this supervisor so a concurrent start cannot trap stop.
        while zerotier_running && [ "$ZEROTIER_PID" = "$stopping_pid" ]; do
            sleep 0.1
        done
    fi
}

zerotier_publish_cli() {
    # KernelSU adds this directory to su's PATH even without system mounts.
    [ "$ZEROTIER_BB" = /data/adb/ksu/bin/busybox ] || return 0
    link=/data/adb/ksu/bin/zerotier-cli
    target=$MODDIR/system/bin/zerotier-cli
    if { [ -e "$link" ] || [ -L "$link" ]; } && [ "$(readlink "$link")" != "$target" ]; then
        zerotier_message 'An existing zerotier-cli command belongs to another installation.' '已有的 zerotier-cli 命令属于其他安装。' >&2
        return 1
    fi
    ln -sf "$target" "$link"
}

zerotier_remove_cli() {
    link=/data/adb/ksu/bin/zerotier-cli
    if [ "$(readlink "$link")" = "$MODDIR/system/bin/zerotier-cli" ]; then
        rm -f "$link"
    fi
}

zerotier_configure_interface_name() (
    network_id=$(printf '%s' "$1" | tr 'A-F' 'a-f')
    case "$network_id" in ''|*[!0-9a-f]*) return 0 ;; esac
    [ "${#network_id}" = 16 ] || return 0
    read -r interface_naming < "$MODDIR/interface-naming"
    case "$interface_naming" in
        ethernet) interface_name=ethzt${network_id#??????} ;;
        default) interface_name= ;;
        *) zerotier_message 'Invalid interface naming selection.' '网卡命名选项无效。' >&2; exit 1 ;;
    esac
    exec 8>"$ZEROTIER_RUN/devicemap.lock"
    "$ZEROTIER_BB" flock 8 || exit 1
    touch "$ZEROTIER_HOME/devicemap"
    # shellcheck disable=SC2016
    "$ZEROTIER_BB" awk -F= -v network_id="$network_id" -v interface_name="$interface_name" '
        interface_name != "" && $1 != network_id && $2 == interface_name { conflict = 1; exit 1 }
        $1 != network_id { print }
        END { if (!conflict && interface_name != "") print network_id "=" interface_name }
    ' "$ZEROTIER_HOME/devicemap" > "$ZEROTIER_RUN/devicemap.new" || {
        rm -f "$ZEROTIER_RUN/devicemap.new"
        zerotier_message 'Interface name already assigned: %s' '网卡名称已被占用：%s' "$interface_name" >&2
        exit 1
    }
    mv -f "$ZEROTIER_RUN/devicemap.new" "$ZEROTIER_HOME/devicemap"
)
