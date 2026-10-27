#!/bin/sh
set -eu
COMPILER=$1
shift
for ARGUMENT in "$@"; do
    case "$ARGUMENT" in
        */osfmk/prng/prng_random.c) set -- "$@" -Wno-error=format ;;
    esac
done
exec xcrun --sdk macosx "$COMPILER" "$@" -Wno-reserved-identifier -Wno-error=unused-but-set-variable -Wno-error=pointer-to-int-cast -Wno-error=gnu-folding-constant
