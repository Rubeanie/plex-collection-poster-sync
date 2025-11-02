#!/bin/bash

printenv > /etc/default/locale; # Needed so cron can access env variables

# Check if CRON_SCHEDULE is set
if [ -n "${CRON_SCHEDULE+1}" ]; then
  echo "\$CRON_SCHEDULE is set: $CRON_SCHEDULE"
  CRON_EXPRESSION=${CRON_SCHEDULE}
else
  echo "\$CRON_SCHEDULE is not set, using default: 0 */8 * * *"
  CRON_EXPRESSION="0 */8 * * *"
fi

# Set up cron job
/usr/bin/crontab -l | { cat; echo "$CRON_EXPRESSION /usr/local/bin/python /app/collection_poster_sync.py >> /var/log/cron.log 2>&1"; } | /usr/bin/crontab -

# Check if RUN_ON_CREATION is enabled
if [ -n "${RUN_ON_CREATION+1}" ] && [ "$RUN_ON_CREATION" = "true" ]; then
  echo "RUN NOW"
  /usr/local/bin/python /app/collection_poster_sync.py
  echo ""
  echo "[ENTRYPOINT] Starting cron in foreground..."
  /etc/init.d/cron start && tail -f /var/log/cron.log
else
  echo "RUN_ON_CREATION is disabled, script will run on CRON schedule"
  /etc/init.d/cron start && tail -f /var/log/cron.log
fi
