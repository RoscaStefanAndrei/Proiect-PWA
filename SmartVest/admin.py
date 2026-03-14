from django.contrib import admin
from .models import (
    AnalysisHistory,
    Notification,
    NotificationPreference,
    PriceAlert,
    SavedPortfolio,
    UserProfile,
)

admin.site.register(SavedPortfolio)
admin.site.register(UserProfile)
admin.site.register(AnalysisHistory)
admin.site.register(Notification)
admin.site.register(NotificationPreference)
admin.site.register(PriceAlert)
