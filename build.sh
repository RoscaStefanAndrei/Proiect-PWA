#!/usr/bin/env bash
# Render build script
set -o errexit

pip install --upgrade pip
pip install -r requirements.txt

python manage.py collectstatic --no-input
python manage.py migrate

# Create superuser from env vars (skips if already exists)
if [ -n "$DJANGO_SUPERUSER_USERNAME" ]; then
    python manage.py createsuperuser --no-input || true
    # Update password in case it changed
    if [ -n "$DJANGO_SUPERUSER_PASSWORD" ]; then
        python -c "
import django; django.setup()
from django.contrib.auth import get_user_model
import os
User = get_user_model()
try:
    u = User.objects.get(username=os.environ['DJANGO_SUPERUSER_USERNAME'])
    u.set_password(os.environ['DJANGO_SUPERUSER_PASSWORD'])
    u.save()
    print(f'Password updated for {u.username}')
except User.DoesNotExist:
    print('Superuser not found')
"
    fi
fi
