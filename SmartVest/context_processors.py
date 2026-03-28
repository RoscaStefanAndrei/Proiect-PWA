from django.conf import settings

from .models import Notification


def notification_context(request):
    if request.user.is_authenticated:
        count = Notification.objects.filter(user=request.user, is_read=False).count()
        return {
            'unread_count': count,
            'vapid_public_key': getattr(settings, 'VAPID_PUBLIC_KEY', ''),
        }
    return {}
