#!/system/bin/sh

MODDIR=${0%/*}
# shellcheck source=module/lib.sh
. "$MODDIR/lib.sh"
sh "$MODDIR/control.sh" stop
zt_remove_cli
# Keep the identity and network memberships for reinstallation.
