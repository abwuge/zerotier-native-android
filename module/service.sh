#!/system/bin/sh

MODDIR=${0%/*}
# shellcheck source=module/lib.sh
. "$MODDIR/lib.sh"
zt_init

# The lock descriptor belongs only to this supervisor, never to its children.
exec 9>"$ZT_RUN/service.lock"
"$ZT_BB" flock -n 9 || exit 0
[ ! -f "$MODDIR/disable" ] && [ ! -f "$MODDIR/remove" ] || exit 0
echo "$$" > "$ZT_RUN/service.pid"

daemon_pid=
adapter_pid=
network_pid=
delay_pid=
cleanup() {
    trap '' TERM INT HUP
    for pid in "$daemon_pid" "$adapter_pid" "$network_pid" "$delay_pid"; do
        [ -z "$pid" ] || kill "$pid" 2>/dev/null
    done
    for pid in "$daemon_pid" "$adapter_pid" "$network_pid" "$delay_pid"; do
        [ -z "$pid" ] || wait "$pid" 2>/dev/null
    done
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

"$ZT_BB" sh "$MODDIR/routes.sh" "$$" 9>&- &
adapter_pid=$!

"$ZT_BB" sh "$MODDIR/network.sh" 9>&- &
network_pid=$!

while [ ! -f "$MODDIR/disable" ] && [ ! -f "$MODDIR/remove" ]; do
    "$MODDIR/bin/zerotier-one" "$ZT_HOME" 9>&- &
    daemon_pid=$!
    wait "$daemon_pid"
    result=$?
    daemon_pid=
    echo "zerotier-one exited ($result); restarting in 5 seconds."
    sleep 5 9>&- &
    delay_pid=$!
    wait "$delay_pid"
    delay_pid=
done
