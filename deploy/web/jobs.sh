#!/bin/sh
# The scheduled jobs of a farm's server (deploy/compose.yml service `jobs`; README, Management commands), as the app
# role, in one loop:
#   every JOBS_BROKER_SECONDS (60)  sensor_broker_sync: the broker's passwd and acl from the Sensors configuration (a
#                                   credential or device changed on the pages reaches the broker within a minute plus
#                                   the broker's own 5 s), with the ingest's own broker user (SENSORS_BROKER_EXTRA)
#   every JOBS_TASKS_SECONDS (3600) generate_tasks: the planned tasks of the recurring tasks
#   once a day                      sensors_housekeeping: dead letters older than 90 days
# A failing job is logged and tried again at its next turn; the loop goes on. /tmp/jobs.alive is touched on every
# turn: the container's health check fails when it is older than 10 minutes.
# The alarms are not here: they are the alarm worker's (deploy/compose.yml, the `alarms` slot).
set -u
cd /app || exit 1
BROKER_EVERY=${JOBS_BROKER_SECONDS:-60}
TASKS_EVERY=${JOBS_TASKS_SECONDS:-3600}
broker_last=0 tasks_last=0 housekeeping_day=

run() {
  echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) jobs: $*"
  python manage.py "$@" || echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) jobs: ERROR: $1 failed (exit $?)"
}

trap 'exit 0' TERM INT
while :; do
  now=$(date -u +%s)
  if [ $(( now - broker_last )) -ge "$BROKER_EVERY" ]; then
    if [ -n "${SENSORS_BROKER_EXTRA:-}" ]; then
      run sensor_broker_sync --extra "$SENSORS_BROKER_EXTRA"
    else
      run sensor_broker_sync
    fi
    broker_last=$now
  fi
  if [ $(( now - tasks_last )) -ge "$TASKS_EVERY" ]; then
    run generate_tasks
    tasks_last=$now
  fi
  today=$(date -u +%Y-%m-%d)
  if [ "$today" != "$housekeeping_day" ]; then
    run sensors_housekeeping
    housekeeping_day=$today
  fi
  touch /tmp/jobs.alive
  sleep 15 &
  wait $!
done
