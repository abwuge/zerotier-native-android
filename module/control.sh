#!/system/bin/sh

MODDIR=${0%/*}
# shellcheck source=module/lib.sh
. "$MODDIR/lib.sh"
zt_init

stop_service() {
    if zt_running; then
        stopping_pid=$ZT_PID
        kill -TERM "$ZT_PID" || return 1
        # Android mksh closes auxiliary descriptors when executing flock.
        # Wait only for the supervisor being stopped, including its cleanup.
        while zt_running && [ "$ZT_PID" = "$stopping_pid" ]; do
            sleep 0.1
        done
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
