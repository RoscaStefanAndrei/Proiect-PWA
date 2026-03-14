from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.models import User

from .models import NotificationPreference, SavedPortfolio, UserProfile


class UserRegisterForm(UserCreationForm):
    email = forms.EmailField(required=True)

    class Meta:
        model = User
        fields = ['username', 'email']


class UserUpdateForm(forms.ModelForm):
    email = forms.EmailField()

    class Meta:
        model = User
        fields = ['username', 'email']


class UserProfileForm(forms.ModelForm):
    class Meta:
        model = UserProfile
        fields = ['avatar', 'bio']


class SavedPortfolioForm(forms.ModelForm):
    class Meta:
        model = SavedPortfolio
        fields = ['name', 'description']


class NotificationPreferenceForm(forms.ModelForm):
    class Meta:
        model = NotificationPreference
        fields = [
            'price_alerts_enabled', 'portfolio_alerts_enabled', 'unicorn_alerts_enabled',
            'in_app_enabled', 'email_enabled', 'push_enabled',
            'price_change_threshold', 'portfolio_drawdown_threshold',
        ]
