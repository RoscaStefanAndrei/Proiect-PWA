"""Django email backend using Resend API."""

import logging

import resend
from django.conf import settings
from django.core.mail.backends.base import BaseEmailBackend

logger = logging.getLogger(__name__)


class ResendEmailBackend(BaseEmailBackend):
    """Send emails via the Resend API (https://resend.com)."""

    def __init__(self, fail_silently=False, **kwargs):
        super().__init__(fail_silently=fail_silently, **kwargs)
        resend.api_key = getattr(settings, 'RESEND_API_KEY', '')

    def send_messages(self, email_messages):
        if not resend.api_key:
            logger.warning("RESEND_API_KEY not set — dropping %d email(s)", len(email_messages))
            return 0

        sent = 0
        for msg in email_messages:
            try:
                payload = {
                    'from': msg.from_email or settings.DEFAULT_FROM_EMAIL,
                    'to': list(msg.to),
                    'subject': msg.subject,
                }

                # Prefer HTML content if available, fall back to plain text
                if msg.alternatives:
                    for content, mimetype in msg.alternatives:
                        if mimetype == 'text/html':
                            payload['html'] = content
                            break

                if 'html' not in payload:
                    payload['html'] = msg.body

                if msg.cc:
                    payload['cc'] = list(msg.cc)
                if msg.bcc:
                    payload['bcc'] = list(msg.bcc)
                if msg.reply_to:
                    payload['reply_to'] = msg.reply_to[0]

                resend.Emails.send(payload)
                sent += 1

            except Exception:
                logger.exception("Resend: failed to send email to %s", msg.to)
                if not self.fail_silently:
                    raise

        return sent
