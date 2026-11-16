#!/system/bin/sh

MODDIR=${0%/*}
sh "$MODDIR/control.sh" stop
# Keep the identity and network memberships for reinstallation.
