#!/system/bin/sh

ZEROTIER_HOME=/data/adb/zerotier-native
ZEROTIER_RUN=$ZEROTIER_HOME/run

zerotier_init() {
    [ "$(id -u)" = 0 ] || { echo 'Permission denied.' >&2; exit 1; }
    umask 077
    mkdir -p "$ZEROTIER_RUN"
    chmod 700 "$ZEROTIER_HOME" "$ZEROTIER_RUN"
    for ZEROTIER_BB in /data/adb/magisk/busybox /data/adb/ksu/bin/busybox /data/adb/ap/bin/busybox; do
        [ ! -x "$ZEROTIER_BB" ] || break
    done
    [ -x "$ZEROTIER_BB" ] || { echo 'BusyBox was not found.' >&2; exit 1; }
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
        echo 'An existing zerotier-cli command belongs to another installation.' >&2
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

zerotier_map_network() (
    network=$(printf '%s' "$1" | tr 'A-F' 'a-f')
    case "$network" in ''|*[!0-9a-f]*) return 0 ;; esac
    [ "${#network}" = 16 ] || return 0
    device=ethzt${network#??????}
    exec 8>"$ZEROTIER_RUN/devicemap.lock"
    "$ZEROTIER_BB" flock 8 || exit 1
    touch "$ZEROTIER_HOME/devicemap"
    # shellcheck disable=SC2016
    "$ZEROTIER_BB" awk -F= -v network="$network" -v device="$device" '
        $1 != network && $2 == device { conflict = 1; exit 1 }
        $1 != network { print }
        END { if (!conflict) print network "=" device }
    ' "$ZEROTIER_HOME/devicemap" > "$ZEROTIER_RUN/devicemap.new" || {
        rm -f "$ZEROTIER_RUN/devicemap.new"
        echo "Interface name already assigned: $device" >&2
        exit 1
    }
    mv -f "$ZEROTIER_RUN/devicemap.new" "$ZEROTIER_HOME/devicemap"
)
