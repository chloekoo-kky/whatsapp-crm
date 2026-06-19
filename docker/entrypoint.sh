#!/bin/sh
set -e

# Command override (e.g. Railway cron service: "python manage.py run_whatsapp_batch").
# Run it directly and exit — no migrate, no gunicorn.
if [ "$#" -gt 0 ]; then
  exec "$@"
fi

python manage.py migrate --noinput

# In dev (DJANGO_DEBUG=true), reload when mounted code changes so Gunicorn does not
# keep pre-rename models (e.g. Clinic → Lead) in worker memory. Gunicorn reload needs 1 worker.
WORKERS="${GUNICORN_WORKERS:-2}"
RELOAD=""
case "${DJANGO_DEBUG:-True}" in
  1|true|True|yes|YES)
    RELOAD="--reload"
    WORKERS=1
    ;;
esac

exec gunicorn clinic_crm.wsgi:application \
  --bind "0.0.0.0:${PORT:-8000}" \
  --workers "$WORKERS" \
  --timeout "${GUNICORN_TIMEOUT:-120}" \
  $RELOAD \
  --access-logfile - \
  --error-logfile -
