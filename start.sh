#!/bin/bash
set -euo pipefail

# Check if CRON_SCHEDULE is set
if [ -n "${CRON_SCHEDULE+1}" ]; then
  echo "\$CRON_SCHEDULE is set: $CRON_SCHEDULE"
  CRON_EXPRESSION=${CRON_SCHEDULE}
else
  echo "\$CRON_SCHEDULE is not set, using default: 0 */8 * * *"
  CRON_EXPRESSION="0 */8 * * *"
fi

# Create crontab file for supercronic (created at runtime to ensure proper permissions)
echo "$CRON_EXPRESSION /usr/local/bin/python /app/collection_poster_sync.py >> /app/cron.log 2>&1" > /app/crontab

# Verify supercronic is executable
if [ ! -x /usr/local/bin/supercronic ]; then
  echo "ERROR: supercronic is not executable or not found" >&2
  exit 1
fi

# Check if RUN_ON_CREATION is enabled
if [ -n "${RUN_ON_CREATION+1}" ] && [ "$RUN_ON_CREATION" = "true" ]; then
  echo "RUN NOW"
  /usr/local/bin/python /app/collection_poster_sync.py
  echo ""
  echo "[ENTRYPOINT] Starting supercronic in foreground..."
  exec /usr/local/bin/supercronic /app/crontab
else
  echo "RUN_ON_CREATION is disabled, script will run on CRON schedule"
  echo "[ENTRYPOINT] Starting supercronic in foreground..."
  exec /usr/local/bin/supercronic /app/crontab
fi
