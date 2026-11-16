#!/system/bin/sh

MODDIR=${0%/*}
# shellcheck source=module/lib.sh
. "$MODDIR/lib.sh"
zt_init

stop_service() {
    if zt_running; then
        kill -TERM "$ZT_PID" || return 1
        # Wait for route and daemon cleanup via the supervisor's lock.
        exec 8>"$ZT_RUN/service.lock"
        "$ZT_BB" flock 8
        "$ZT_BB" flock -u 8
        exec 8>&-
    fi
}

start_service() {
    [ ! -f "$MODDIR/disable" ] && [ ! -f "$MODDIR/remove" ] || {
        echo 'Enable the module in your root manager before starting it.' >&2
        return 1
    }
    "$ZT_BB" sh "$MODDIR/service.sh" </dev/null >/dev/null 2>&1 &
}

case "$1" in
    start) start_service ;;
    stop) stop_service ;;
    restart) stop_service && start_service ;;
    *) exit 1 ;;
esac
