from django.contrib import admin
from .models import SavedPortfolio, UserProfile, AnalysisHistory

admin.site.register(SavedPortfolio)
admin.site.register(UserProfile)
admin.site.register(AnalysisHistory)
