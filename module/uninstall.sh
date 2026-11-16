#!/system/bin/sh

MODDIR=${0%/*}
# shellcheck source=module/lib.sh
. "$MODDIR/lib.sh"
zt_init
zt_stop
zt_remove_cli
# Keep the identity and network memberships for reinstallation.
