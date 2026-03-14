"""
SmartVest Notification Dispatcher
=================================
Central function for sending notifications across all channels.
Phase 1: In-app only. Email and push added in later phases.
"""

import logging

from .models import Notification, NotificationPreference

logger = logging.getLogger(__name__)

# Map notification type to preference field name
_TYPE_TO_PREF = {
    Notification.Type.PRICE_ALERT: 'price_alerts_enabled',
    Notification.Type.PORTFOLIO_ALERT: 'portfolio_alerts_enabled',
    Notification.Type.UNICORN_FOUND: 'unicorn_alerts_enabled',
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

    # Channel 2: Email (Phase 3 — placeholder)
    # if prefs.email_enabled:
    #     _send_email_notification(user, title, message, link)

    # Channel 3: Push (Phase 4 — placeholder)
    # if prefs.push_enabled:
    #     _send_push_notification(user, title, message, link)
