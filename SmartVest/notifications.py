"""
SmartVest Notification Dispatcher
=================================
Central function for sending notifications across all channels.
Channels: in-app (Phase 1), email via Resend (Phase 3), push via VAPID (Phase 4).
"""

import json
import logging

from django.conf import settings
from django.template.loader import render_to_string

from .models import Notification, NotificationPreference

logger = logging.getLogger(__name__)

# Map notification type to preference field name
_TYPE_TO_PREF = {
    Notification.Type.PRICE_ALERT: 'price_alerts_enabled',
    Notification.Type.PORTFOLIO_ALERT: 'portfolio_alerts_enabled',
    Notification.Type.UNICORN_FOUND: 'unicorn_alerts_enabled',
}

# Icons / colors used in email templates per notification type
_TYPE_META = {
    Notification.Type.PRICE_ALERT: {
        'icon': 'chart-line', 'color': '#f59e0b', 'label': 'Price Alert',
    },
    Notification.Type.PORTFOLIO_ALERT: {
        'icon': 'briefcase', 'color': '#3b82f6', 'label': 'Portfolio Alert',
    },
    Notification.Type.UNICORN_FOUND: {
        'icon': 'star', 'color': '#10b981', 'label': 'New Unicorn',
    },
}


def send_notification(user, notification_type, title, message, link=''):
    """
    Send a notification to a user across enabled channels.

    Args:
        user: Django User instance
        notification_type: Notification.Type value
        title: Short notification title
        message: Notification body text
        link: Relative URL to navigate to (e.g. "/unicorns/watchlist/")
    """
    prefs, _ = NotificationPreference.objects.get_or_create(user=user)

    # Check if this notification type is enabled
    pref_field = _TYPE_TO_PREF.get(notification_type)
    if pref_field and not getattr(prefs, pref_field, True):
        logger.debug("Notification type %s disabled for user %s", notification_type, user.username)
        return

    # Channel 1: In-app notification
    if prefs.in_app_enabled:
        Notification.objects.create(
            user=user,
            notification_type=notification_type,
            title=title,
            message=message,
            link=link,
        )
        logger.info("In-app notification sent to %s: %s", user.username, title)

    # Channel 2: Email via Resend
    if prefs.email_enabled:
        _send_email_notification(user, notification_type, title, message, link)

    # Channel 3: Push via VAPID / Web Push
    if prefs.push_enabled:
        _send_push_notification(user, title, message, link)


# ---------------------------------------------------------------------------
# Email (Resend)
# ---------------------------------------------------------------------------

def _send_email_notification(user, notification_type, title, message, link):
    """Send an email notification via Resend."""
    api_key = getattr(settings, 'RESEND_API_KEY', '')
    if not api_key:
        logger.debug("RESEND_API_KEY not set — skipping email for %s", user.username)
        return

    email = user.email
    if not email:
        logger.debug("No email address for user %s — skipping", user.username)
        return

    try:
        import resend
        resend.api_key = api_key

        # Build full URL for email link
        full_link = ''
        if link:
            domain = getattr(settings, 'SITE_DOMAIN', '')
            if domain:
                scheme = 'http' if settings.DEBUG else 'https'
                full_link = f"{scheme}://{domain}{link}"

        meta = _TYPE_META.get(notification_type, _TYPE_META[Notification.Type.PRICE_ALERT])

        html = render_to_string('email/notification.html', {
            'title': title,
            'message': message,
            'link': full_link,
            'meta': meta,
            'user': user,
        })

        resend.Emails.send({
            'from': settings.DEFAULT_FROM_EMAIL,
            'to': [email],
            'subject': f"SmartVest — {title}",
            'html': html,
        })

        logger.info("Email sent to %s (%s): %s", user.username, email, title)

    except Exception:
        logger.exception("Failed to send email to %s", user.username)


# ---------------------------------------------------------------------------
# Push (VAPID / Web Push)
# ---------------------------------------------------------------------------

def _send_push_notification(user, title, message, link):
    """Send a push notification to all of the user's subscribed browsers."""
    vapid_private = getattr(settings, 'VAPID_PRIVATE_KEY', '')
    vapid_email = getattr(settings, 'VAPID_ADMIN_EMAIL', '')
    if not vapid_private or not vapid_email:
        logger.debug("VAPID keys not configured — skipping push for %s", user.username)
        return

    from .models import PushSubscription

    subs = list(PushSubscription.objects.filter(user=user))
    if not subs:
        return

    try:
        from pywebpush import webpush, WebPushException
    except ImportError:
        logger.warning("pywebpush not installed — skipping push")
        return

    payload = json.dumps({'title': title, 'message': message, 'link': link})

    for sub in subs:
        try:
            webpush(
                subscription_info={
                    'endpoint': sub.endpoint,
                    'keys': {'p256dh': sub.p256dh, 'auth': sub.auth},
                },
                data=payload,
                vapid_private_key=vapid_private,
                vapid_claims={'sub': f'mailto:{vapid_email}'},
            )
            logger.info("Push sent to %s (endpoint …%s)", user.username, sub.endpoint[-20:])
        except WebPushException as e:
            # 404/410 = subscription expired or unsubscribed
            status = getattr(getattr(e, 'response', None), 'status_code', None)
            if status in (404, 410):
                sub.delete()
                logger.info("Removed expired push subscription for %s", user.username)
            else:
                logger.warning("Push failed for %s: %s", user.username, e)
        except Exception:
            logger.exception("Unexpected push error for %s", user.username)
