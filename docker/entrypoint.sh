#!/bin/sh
set -e

python manage.py migrate --noinput
python manage.py collectstatic --noinput

# Prepare the AI model's meaning vectors for approved studies that don't have
# them yet. Runs in the background so the site starts right away; checks use
# TF-IDF for any study that isn't ready yet.
python manage.py build_semantic_index > /tmp/build_semantic_index.log 2>&1 &

exec "$@"
