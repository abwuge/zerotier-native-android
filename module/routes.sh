#!/system/bin/sh
# shellcheck shell=busybox

MODDIR=${0%/*}
# shellcheck source=module/lib.sh
. "$MODDIR/lib.sh"
zt_init
set -f
export LC_ALL=C
ZT_TABLE=19993
ZT_PRIORITY=19500
ZT_PROTOCOL=199
ZT_IP=/system/bin/ip
supervisor_pid=$1
monitor_pid=

# shellcheck disable=SC2329
cleanup() {
    trap '' TERM INT HUP
    [ -z "$monitor_pid" ] || kill "$monitor_pid" 2>/dev/null
    [ -z "$monitor_pid" ] || wait "$monitor_pid" 2>/dev/null
    for family in -4 -6; do
        occupied=$("$ZT_IP" "$family" rule show | awk -v p="$ZT_PRIORITY:" '$1 == p { $1=$1; print }')
        expected="$ZT_PRIORITY: from all iif lo lookup $ZT_TABLE"
        if [ "$occupied" = "$expected" ]; then
            "$ZT_IP" "$family" rule del pref "$ZT_PRIORITY" iif lo lookup "$ZT_TABLE"
        fi
        "$ZT_IP" "$family" route flush table "$ZT_TABLE" proto "$ZT_PROTOCOL" 2>/dev/null
    done
    rm -f "$ZT_RUN/events" "$ZT_RUN/"*.routes
    # A failed adapter must not leave a running daemon with unusable routing.
    kill -TERM "$supervisor_pid" 2>/dev/null
}
trap 'exit 0' TERM INT HUP
trap cleanup EXIT

normalize() {
    awk -v overlay_only="$1" '
        {
            dev = ""; line = ""; down = 0
            for (i = 1; i <= NF; i++) {
                if ($i == "dev") dev = $(i+1)
                if ($i == "table" || $i == "proto" || $i == "expires") { i++; continue }
                if ($i == "linkdown") { down = 1; continue }
                line = line (line == "" ? "" : " ") $i
            }
            if (!overlay_only || (!down && dev ~ /^zt[0-9a-z]+$/)) print line
        }
    ' | sort -u
}

sync_family() {
    family=$1
    wanted=$ZT_RUN/$family.wanted.routes
    actual=$ZT_RUN/$family.actual.routes
    rules=$("$ZT_IP" "$family" rule show) || return 1
    occupied=$(printf '%s\n' "$rules" | awk -v p="$ZT_PRIORITY:" '$1 == p { $1=$1; print }')
    expected="$ZT_PRIORITY: from all iif lo lookup $ZT_TABLE"
    if [ -n "$occupied" ] && [ "$occupied" != "$expected" ]; then
        echo "Policy rule priority $ZT_PRIORITY is already in use: $occupied" >&2
        return 1
    fi

    "$ZT_IP" "$family" -o route show table main > "$ZT_RUN/main.routes" || return 1
    normalize 1 < "$ZT_RUN/main.routes" > "$wanted"
    # A table-specific dump can fail while that table has no routes yet.
    "$ZT_IP" "$family" -o route show table all > "$ZT_RUN/all.routes" || return 1
    awk -v table="$ZT_TABLE" -v protocol="$ZT_PROTOCOL" '
        {
            t = ""; p = ""
            for (i = 1; i < NF; i++) {
                if ($i == "table") t = $(i+1)
                if ($i == "proto") p = $(i+1)
            }
            if (t == table) {
                if (p != protocol) exit 1
                print
            }
        }
    ' < "$ZT_RUN/all.routes" > "$ZT_RUN/table.routes" || {
        echo "Route table $ZT_TABLE contains routes owned by another service." >&2
        return 1
    }
    normalize 0 < "$ZT_RUN/table.routes" > "$actual"

    # Delete and add exact route differences; unchanged paths never disappear.
    while IFS= read -r route; do
        if ! grep -Fxq "$route" "$wanted"; then
            # Kernel-generated words are split as ip arguments, never evaluated.
            # shellcheck disable=SC2086
            if ! "$ZT_IP" "$family" route del table "$ZT_TABLE" $route 2>"$ZT_RUN/error.routes"; then
                sync_incomplete=2
                sync_error=$(cat "$ZT_RUN/error.routes")
            fi
        fi
    done < "$actual"
    # Gateways must be reachable in this table before routed prefixes are added.
    awk '!/ via /' "$wanted" > "$ZT_RUN/add.routes"
    awk '/ via /' "$wanted" >> "$ZT_RUN/add.routes"
    while IFS= read -r route; do
        if ! grep -Fxq "$route" "$actual"; then
            # shellcheck disable=SC2086
            if ! "$ZT_IP" "$family" route append table "$ZT_TABLE" proto "$ZT_PROTOCOL" $route 2>"$ZT_RUN/error.routes"; then
                sync_incomplete=2
                sync_error=$(cat "$ZT_RUN/error.routes")
            fi
        fi
    done < "$ZT_RUN/add.routes"

    if [ -z "$occupied" ]; then
        "$ZT_IP" "$family" rule add pref "$ZT_PRIORITY" iif lo lookup "$ZT_TABLE" || return 1
    fi
}

sync_routes() {
    sync_incomplete=0
    sync_error=
    sync_family -4 && sync_family -6 || return 1
    return "$sync_incomplete"
}

rm -f "$ZT_RUN/events"
mkfifo -m 600 "$ZT_RUN/events" || exit 1
# Subscribe before taking the initial snapshot so changes queue during sync.
"$ZT_IP" -o monitor link route rule > "$ZT_RUN/events" &
monitor_pid=$!
exec 3<"$ZT_RUN/events"
sync_routes
sync_status=$?
[ "$sync_status" -ne 1 ] || exit 1
while :; do
    if [ "$sync_status" = 2 ]; then
        # Link deletion/recreation can race a snapshot. Process queued changes;
        # after a quiet second, retry once and report a persistent apply error.
        # Timed reads are provided by the root manager's BusyBox ash.
        # shellcheck disable=SC3045
        if ! IFS= read -r -t 1 _event <&3; then
            sync_routes
            sync_status=$?
            if [ "$sync_status" -ne 0 ]; then
                [ -z "$sync_error" ] || printf '%s\n' "$sync_error" >&2
                exit 1
            fi
            continue
        fi
    else
        IFS= read -r _event <&3 || break
    fi
    sync_routes
    sync_status=$?
    [ "$sync_status" -ne 1 ] || exit 1
done
echo 'The route event monitor stopped.' >&2
exit 1
