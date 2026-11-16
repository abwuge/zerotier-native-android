#!/system/bin/sh

MODDIR=${0%/*}
# shellcheck source=module/lib.sh
. "$MODDIR/lib.sh"
zt_init

case "${1:-run}" in
    stop) zt_stop; exit $? ;;
    start|restart)
        [ "$1" != restart ] || zt_stop || exit 1
        [ ! -f "$MODDIR/disable" ] && [ ! -f "$MODDIR/remove" ] || {
            echo 'The module is disabled or marked for removal.' >&2
            exit 1
        }
        "$ZT_BB" sh "$MODDIR/service.sh" run </dev/null >/dev/null 2>&1 &
        exit 0
        ;;
    run) ;;
    *) exit 1 ;;
esac

# The lock descriptor belongs only to this supervisor, never to its children.
exec 9>"$ZT_RUN/service.lock"
"$ZT_BB" flock -n 9 || exit 0
[ ! -f "$MODDIR/disable" ] && [ ! -f "$MODDIR/remove" ] || exit 0
echo "$$" > "$ZT_RUN/service.pid"

process_pid=
adapter_pid=
network_pid=
delay_pid=
stop_children() {
    trap '' TERM INT HUP
    for pid in "$@"; do
        [ -z "$pid" ] || kill "$pid" 2>/dev/null
    done
    for pid in "$@"; do
        [ -z "$pid" ] || wait "$pid" 2>/dev/null
    done
}
cleanup() {
    stop_children "$process_pid" "$adapter_pid" "$network_pid" "$delay_pid"
    rm -f "$ZT_RUN/service.pid"
}
trap 'exit 0' TERM INT HUP
trap cleanup EXIT

# Rotate on service start; credentials and joined networks stay in ZT_HOME.
[ ! -f "$ZT_HOME/service.log" ] || mv -f "$ZT_HOME/service.log" "$ZT_HOME/service.log.1"
exec >>"$ZT_HOME/service.log" 2>&1

if [ ! -c /dev/net/tun ] && [ ! -c /dev/tun ]; then
    echo 'TUN/TAP device is missing; enable CONFIG_TUN in the device kernel.'
    exit 1
fi
zt_publish_cli || exit 1

restart_loop() {
    while [ ! -f "$MODDIR/disable" ] && [ ! -f "$MODDIR/remove" ]; do
        "$@" 9>&- &
        process_pid=$!
        wait "$process_pid"
        result=$?
        process_pid=
        echo "${1##*/} exited ($result); restarting in 5 seconds."
        sleep 5 9>&- &
        delay_pid=$!
        wait "$delay_pid"
        delay_pid=
    done
}
run_network() {
    process_pid=
    delay_pid=
    trap 'exit 0' TERM INT HUP
    trap 'stop_children "$process_pid" "$delay_pid"' EXIT
    export CLASSPATH="$MODDIR/bin/network.jar"
    restart_loop /system/bin/app_process /system/bin org.zerotier.nativeandroid.NetworkAdapter
}

"$ZT_BB" sh "$MODDIR/routes.sh" "$$" 9>&- &
adapter_pid=$!
run_network 9>&- &
network_pid=$!
restart_loop "$MODDIR/bin/zerotier-one" "$ZT_HOME"
