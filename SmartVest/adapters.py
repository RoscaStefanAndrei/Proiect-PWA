from allauth.account.adapter import DefaultAccountAdapter


class SmartVestAccountAdapter(DefaultAccountAdapter):
    """Create UserProfile and NotificationPreference on signup."""

    def save_user(self, request, user, form, commit=True):
        user = super().save_user(request, user, form, commit)
        if commit:
            from .models import NotificationPreference, UserProfile
            UserProfile.objects.get_or_create(user=user)
            NotificationPreference.objects.get_or_create(user=user)
        return user
