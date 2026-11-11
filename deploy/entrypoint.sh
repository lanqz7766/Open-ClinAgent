#!/bin/sh
set -eu
umask 077
mkdir -p "${TMPDIR:-/var/lib/clinagent/tmp}"
exec "$@"
