#!/bin/bash
set -euo pipefail

# Check if CRON_SCHEDULE is set
if [ -n "${CRON_SCHEDULE+1}" ]; then
  CRON_EXPRESSION=${CRON_SCHEDULE}
else
  CRON_EXPRESSION="0 */8 * * *"
fi

# Use /tmp for crontab file (needs to be writable when user is overridden at runtime)
CRONTAB_FILE="/tmp/crontab"

# Create crontab file for supercronic (output to stdout/stderr so docker logs captures it)
echo "$CRON_EXPRESSION /usr/local/bin/python /app/collection_poster_sync.py" > "$CRONTAB_FILE"

# Verify supercronic is executable
if [ ! -x /usr/local/bin/supercronic ]; then
  echo "ERROR: supercronic is not executable or not found" >&2
  exit 1
fi

# Check if RUN_ON_CREATION is enabled
if [ -n "${RUN_ON_CREATION+1}" ] && [ "$RUN_ON_CREATION" = "true" ]; then
  /usr/local/bin/python /app/collection_poster_sync.py
fi

# Start supercronic with -quiet flag to suppress wrapper logs
exec /usr/local/bin/supercronic -quiet "$CRONTAB_FILE"
