#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
shellcheck -s sh -x module/*.sh module/system/bin/* module/META-INF/com/google/android/update-binary build.sh tests/run.sh
exec docker run --rm --network none --cap-add NET_ADMIN \
    -v "$(pwd):/work:ro" zerotier-native-builder python3 /work/tests/integration.py
