#!/bin/sh
set -eu
PROJECT=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
WORK="$PROJECT/../../../scratch/xnu-lab"
DEPENDENCY="$WORK/availability"
EXPECTED=149b1777f3e8c2133042d8e188f72e3adf6a7110
[ "$(git -C "$DEPENDENCY" rev-parse HEAD)" = "$EXPECTED" ]
[ -z "$(git -C "$DEPENDENCY" status --porcelain --untracked-files=all)" ]
OVERLAY="$WORK/availability-sdk"
mkdir -p "$OVERLAY/usr/local/libexec"
ln -sf "$DEPENDENCY/availability.pl" "$OVERLAY/usr/local/libexec/availability.pl"
ln -sf "$DEPENDENCY/availability" "$OVERLAY/usr/local/libexec/availability"
ln -sf "$DEPENDENCY/availability.dsl" "$OVERLAY/usr/local/libexec/availability.dsl"
exec "$WORK/source/bsd/sys/make_symbol_aliasing.sh" "$OVERLAY" "$2"
