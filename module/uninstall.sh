#!/system/bin/sh

MODDIR=${0%/*}
# shellcheck source=module/lib.sh
. "$MODDIR/lib.sh"
zerotier_init
zerotier_stop
zerotier_remove_cli
# Keep the identity and network memberships for reinstallation.
