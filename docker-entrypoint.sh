#!/bin/sh
set -e

# Fly mounts the volume at /data owned by root, so the unprivileged runtime
# user cannot create the cache directory inside it. Fix ownership as root on
# boot, then drop privileges for the actual process.
CACHE_DIR="${MTB_CACHE_DIR:-/data/.mtb_cache}"
mkdir -p "$CACHE_DIR"
chown -R velo:velo "$CACHE_DIR"

exec gosu velo "$@"
