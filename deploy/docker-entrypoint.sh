#!/bin/sh
# Start the hub as whoever owns /data, so a host folder mounted there works on any machine without a chown or a
# uid setting, and a named volume (owned by root when new) is handed to the unprivileged `hub` user.
set -e
if [ "$(id -u)" = "0" ]; then
    owner=$(stat -c %u /data)
    group=$(stat -c %g /data)
    if [ "$owner" = "0" ]; then
        chown hub:hub /data
        owner=$(id -u hub)
        group=$(id -g hub)
    fi
    exec setpriv --reuid="$owner" --regid="$group" --clear-groups "$@"
fi
exec "$@"
