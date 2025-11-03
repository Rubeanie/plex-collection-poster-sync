#!/bin/bash
set -euo pipefail

# Check if CRON_SCHEDULE is set
if [ -n "${CRON_SCHEDULE+1}" ]; then
  CRON_EXPRESSION=${CRON_SCHEDULE}
else
  CRON_EXPRESSION="0 */8 * * *"
fi

# Use /tmp for files that need to be writable when user is overridden at runtime
CRONTAB_FILE="/tmp/crontab"
LOG_FILE="/tmp/cron.log"

# Create crontab file for supercronic (in /tmp to ensure writability when user is overridden)
echo "$CRON_EXPRESSION /usr/local/bin/python /app/collection_poster_sync.py >> $LOG_FILE 2>&1" > "$CRONTAB_FILE"

# Verify supercronic is executable
if [ ! -x /usr/local/bin/supercronic ]; then
  echo "ERROR: supercronic is not executable or not found" >&2
  exit 1
fi

# Check if RUN_ON_CREATION is enabled
if [ -n "${RUN_ON_CREATION+1}" ] && [ "$RUN_ON_CREATION" = "true" ]; then
  /usr/local/bin/python /app/collection_poster_sync.py
fi

# Start supercronic (exec replaces shell process for proper signal handling)
exec /usr/local/bin/supercronic "$CRONTAB_FILE"
