#!/system/bin/sh

ZT_HOME=/data/adb/zerotier-native
ZT_RUN=$ZT_HOME/run

zt_init() {
    [ "$(id -u)" = 0 ] || { echo 'Run this command as root.' >&2; exit 1; }
    umask 077
    mkdir -p "$ZT_RUN"
    chmod 700 "$ZT_HOME" "$ZT_RUN"
    for ZT_BB in /data/adb/magisk/busybox /data/adb/ksu/bin/busybox /data/adb/ap/bin/busybox; do
        [ ! -x "$ZT_BB" ] || break
    done
    [ -x "$ZT_BB" ] || { echo 'Root manager BusyBox was not found.' >&2; exit 1; }
    export ASH_STANDALONE=1
}

zt_running() {
    [ -r "$ZT_RUN/service.pid" ] || return 1
    read -r ZT_PID < "$ZT_RUN/service.pid"
    case "$ZT_PID" in ''|*[!0-9]*) return 1 ;; esac
    [ -r "/proc/$ZT_PID/cmdline" ] || return 1
    tr '\000' '\n' < "/proc/$ZT_PID/cmdline" | grep -Fxq "$MODDIR/service.sh"
}
