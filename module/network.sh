#!/system/bin/sh
# shellcheck shell=busybox

MODDIR=${0%/*}
# shellcheck source=module/lib.sh
. "$MODDIR/lib.sh"
zt_init
export CLASSPATH=$MODDIR/bin/network.jar
process_pid=
delay_pid=
cleanup() {
    trap '' TERM INT HUP
    for pid in "$process_pid" "$delay_pid"; do
        [ -z "$pid" ] || kill "$pid" 2>/dev/null
    done
    for pid in "$process_pid" "$delay_pid"; do
        [ -z "$pid" ] || wait "$pid" 2>/dev/null
    done
}
trap 'exit 0' TERM INT HUP
trap cleanup EXIT

while :; do
    /system/bin/app_process /system/bin org.zerotier.nativeandroid.NetworkAdapter &
    process_pid=$!
    wait "$process_pid"
    result=$?
    process_pid=
    echo "Android network registration exited ($result); restarting in 5 seconds."
    sleep 5 &
    delay_pid=$!
    wait "$delay_pid"
    delay_pid=
done
