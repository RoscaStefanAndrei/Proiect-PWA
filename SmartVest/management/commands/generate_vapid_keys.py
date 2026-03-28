"""Generate VAPID key pair for Web Push notifications."""

import base64

from cryptography.hazmat.primitives.asymmetric import ec
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = 'Generate VAPID key pair for Web Push notifications'

    def handle(self, *args, **options):
        private_key = ec.generate_private_key(ec.SECP256R1())

        # Private key: 32 raw bytes -> URL-safe base64 (no padding)
        raw_private = private_key.private_numbers().private_value.to_bytes(32, 'big')
        priv_b64 = base64.urlsafe_b64encode(raw_private).decode().rstrip('=')

        # Public key: uncompressed EC point (04 || x || y) -> URL-safe base64
        pub_numbers = private_key.public_key().public_numbers()
        raw_public = (
            b'\x04'
            + pub_numbers.x.to_bytes(32, 'big')
            + pub_numbers.y.to_bytes(32, 'big')
        )
        pub_b64 = base64.urlsafe_b64encode(raw_public).decode().rstrip('=')

        self.stdout.write('\nAdd these to your .env file:\n')
        self.stdout.write(f'VAPID_PRIVATE_KEY={priv_b64}')
        self.stdout.write(f'VAPID_PUBLIC_KEY={pub_b64}')
        self.stdout.write(f'VAPID_ADMIN_EMAIL=admin@yourdomain.com\n')
