#!/usr/bin/env bash
# Update the live site on PythonAnywhere:  bash ~/nexusdown-main/deploy.sh
set -euo pipefail

WSGI_FILE="${WSGI_FILE:-/var/www/ismoiljon_pythonanywhere_com_wsgi.py}"
PYTHON="${PYTHON:-python3.13}"

cd "$(dirname "$0")"
git pull --ff-only origin main
"$PYTHON" manage.py migrate --noinput
"$PYTHON" manage.py check
# The "Reload" button on the Web tab has proven unreliable; touching the WSGI file always reloads.
touch "$WSGI_FILE"
echo "Deployed $(git log --oneline -1)"
