"""
SmartVest Views
===============
All view functions and class-based views for the SmartVest application.

Tier 1 improvements applied:
- Consolidated imports (no duplicates)
- Thread-safe state management via Django cache (replaces global mutable dicts)
- CSRF enforcement on all POST endpoints
- Input validation and sanitization
- Proper error handling with try/except on all external API calls
- Python logging replaces print() statements
- Require POST for all destructive/mutating operations
"""

import datetime
import json
import logging
import math
import os
import re
import subprocess
import sys
import tempfile
import threading

import pandas as pd

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.contrib.auth.models import User
from django.core.cache import cache
from django.db import models as db_models
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse_lazy
from django.utils.decorators import method_decorator
from django.views.decorators.http import require_POST, require_http_methods
from django.views.generic import DeleteView, DetailView, ListView

from .forms import (
    NotificationPreferenceForm,
    SavedPortfolioForm,
    UserProfileForm,
    UserRegisterForm,
    UserUpdateForm,
)
from .models import (
    BacktestRun,
    FilterPreset,
    Notification,
    NotificationPreference,
    PriceAlert,
    PushSubscription,
    SavedPortfolio,
    UserProfile,
    WatchedUnicorn,
)
from .utils import fetch_prices_cached, get_portfolio_performance

logger = logging.getLogger(__name__)

# Add project root to path for importing standalone scripts
if str(settings.BASE_DIR) not in sys.path:
    sys.path.insert(0, str(settings.BASE_DIR))


# ============================================================================
# THREAD-SAFE STATE HELPERS (replaces global mutable variables)
# ============================================================================

# Cache keys
ALGO_RUNNING_KEY = "smartvest_algo_running"
BACKTEST_PROGRESS_KEY = "smartvest_backtest_progress"

# Default backtest progress state
_DEFAULT_BACKTEST_PROGRESS = {
    'percent': 0,
    'message': 'Idle',
    'running': False,
    'result': None,
}


def _get_algo_running():
    """Thread-safe check if algorithm is running."""
    return cache.get(ALGO_RUNNING_KEY, False)


def _set_algo_running(value):
    """Thread-safe set algorithm running state."""
    cache.set(ALGO_RUNNING_KEY, value, timeout=3600)  # 1 hour max


def _get_backtest_progress():
    """Thread-safe get backtest progress."""
    return cache.get(BACKTEST_PROGRESS_KEY, _DEFAULT_BACKTEST_PROGRESS.copy())


def _set_backtest_progress(progress):
    """Thread-safe set backtest progress."""
    cache.set(BACKTEST_PROGRESS_KEY, progress, timeout=7200)  # 2 hour max


# ============================================================================
# CONSTANTS
# ============================================================================

# Validation constants
MAX_PORTFOLIO_NAME_LENGTH = 100
MAX_BUDGET = 10_000_000  # $10M cap
MIN_BUDGET = 100  # $100 minimum
VALID_PROFILE_TYPES = ('conservative', 'balanced', 'aggressive')
MAX_PRESET_NAME_LENGTH = 100

# All available Finviz filters organized by category
FINVIZ_FILTERS = {
    'descriptive': {
        'Exchange': ['Any', 'AMEX', 'NASDAQ', 'NYSE'],
        'Market Cap.': [
            'Any', 'Mega ($200bln and more)', 'Large ($10bln to $200bln)',
            '+Large (over $10bln)', 'Mid ($2bln to $10bln)', '+Mid (over $2bln)',
            'Small ($300mln to $2bln)', '+Small (over $300mln)',
            'Micro ($50mln to $300mln)', 'Nano (under $50mln)',
        ],
        'Dividend Yield': [
            'Any', 'None (0%)', 'Positive (>0%)', 'High (>5%)', 'Very High (>10%)',
        ],
        'Average Volume': [
            'Any', 'Under 50K', 'Under 100K', 'Under 500K', 'Under 750K',
            'Under 1M', 'Over 50K', 'Over 100K', 'Over 200K', 'Over 300K',
            'Over 400K', 'Over 500K', 'Over 750K', 'Over 1M', 'Over 2M',
        ],
        'Relative Volume': [
            'Any', 'Over 0.25', 'Over 0.5', 'Over 1', 'Over 1.5', 'Over 2',
            'Over 3', 'Over 5', 'Over 10', 'Under 0.5', 'Under 0.75',
            'Under 1', 'Under 1.5', 'Under 2',
        ],
        'Float': [
            'Any', 'Under 1M', 'Under 5M', 'Under 10M', 'Under 20M',
            'Under 50M', 'Under 100M', 'Over 1M', 'Over 2M', 'Over 5M',
            'Over 10M', 'Over 20M', 'Over 50M', 'Over 100M', 'Over 200M',
            'Over 500M',
        ],
        'Sector': [
            'Any', 'Basic Materials', 'Communication Services',
            'Consumer Cyclical', 'Consumer Defensive', 'Energy', 'Financial',
            'Healthcare', 'Industrials', 'Real Estate', 'Technology', 'Utilities',
        ],
        'Industry': ['Any'],
        'Country': [
            'Any', 'USA', 'Foreign (ex-USA)', 'China', 'Japan', 'UK',
            'Canada', 'Germany', 'France',
        ],
    },
    'fundamental': {
        'P/E': [
            'Any', 'Low (<15)', 'Profitable (>0)', 'High (>50)', 'Under 5',
            'Under 10', 'Under 15', 'Under 20', 'Under 25', 'Under 30',
            'Under 35', 'Under 40', 'Under 45', 'Under 50', 'Over 5',
            'Over 10', 'Over 15', 'Over 20', 'Over 25', 'Over 30',
            'Over 35', 'Over 40', 'Over 50',
        ],
        'Forward P/E': [
            'Any', 'Low (<15)', 'Profitable (>0)', 'High (>50)', 'Under 5',
            'Under 10', 'Under 15', 'Under 20', 'Under 25', 'Under 30',
            'Over 5', 'Over 10', 'Over 15', 'Over 20', 'Over 25', 'Over 30',
            'Over 35', 'Over 40', 'Over 50',
        ],
        'PEG': [
            'Any', 'Low (<1)', 'High (>2)', 'Under 1', 'Under 2', 'Under 3',
            'Over 1', 'Over 2', 'Over 3',
        ],
        'P/S': [
            'Any', 'Low (<1)', 'High (>10)', 'Under 1', 'Under 2', 'Under 3',
            'Under 4', 'Under 5', 'Under 6', 'Under 7', 'Under 8', 'Under 9',
            'Under 10', 'Over 1', 'Over 2', 'Over 3', 'Over 4', 'Over 5',
            'Over 6', 'Over 7', 'Over 8', 'Over 9', 'Over 10',
        ],
        'P/B': [
            'Any', 'Low (<1)', 'High (>5)', 'Under 1', 'Under 2', 'Under 3',
            'Under 4', 'Under 5', 'Under 6', 'Under 7', 'Under 8', 'Under 9',
            'Under 10', 'Over 1', 'Over 2', 'Over 3', 'Over 4', 'Over 5',
            'Over 6', 'Over 7', 'Over 8', 'Over 9', 'Over 10',
        ],
        'EPS growthnext 5 years': [
            'Any', 'Negative (<0%)', 'Positive (>0%)', 'Under 5%', 'Under 10%',
            'Under 15%', 'Under 20%', 'Under 25%', 'Under 30%', 'Over 5%',
            'Over 10%', 'Over 15%', 'Over 20%', 'Over 25%', 'Over 30%',
        ],
        'EPS growththis year': [
            'Any', 'Negative (<0%)', 'Positive (>0%)', 'Over 5%', 'Over 10%',
            'Over 15%', 'Over 20%', 'Over 25%', 'Over 30%',
        ],
        'EPS growthnext year': [
            'Any', 'Negative (<0%)', 'Positive (>0%)', 'Over 5%', 'Over 10%',
            'Over 15%', 'Over 20%', 'Over 25%', 'Over 30%',
        ],
        'Return on Equity': [
            'Any', 'Positive (>0%)', 'Negative (<0%)', 'Very Positive (>30%)',
            'Over +5%', 'Over +10%', 'Over +15%', 'Over +20%', 'Over +25%',
            'Over +30%', 'Under +5%', 'Under +10%', 'Under +15%', 'Under +20%',
            'Under +25%', 'Under +30%', 'Under -15%', 'Under -30%',
        ],
        'Return on Assets': [
            'Any', 'Positive (>0%)', 'Negative (<0%)', 'Very Positive (>15%)',
            'Over +5%', 'Over +10%', 'Over +15%', 'Over +20%', 'Over +25%',
        ],
        'Return on Investment': [
            'Any', 'Positive (>0%)', 'Negative (<0%)', 'Very Positive (>25%)',
            'Over +5%', 'Over +10%', 'Over +15%', 'Over +20%', 'Over +25%',
        ],
        'Current Ratio': [
            'Any', 'High (>3)', 'Low (<1)', 'Under 1', 'Under 0.5', 'Over 0.5',
            'Over 1', 'Over 1.5', 'Over 2', 'Over 3', 'Over 4', 'Over 5',
            'Over 10',
        ],
        'Debt/Equity': [
            'Any', 'High (>0.5)', 'Low (<0.1)', 'Under 0.1', 'Under 0.2',
            'Under 0.3', 'Under 0.4', 'Under 0.5', 'Under 0.6', 'Under 0.7',
            'Under 0.8', 'Under 0.9', 'Under 1', 'Over 0.1', 'Over 0.2',
            'Over 0.3', 'Over 0.4', 'Over 0.5', 'Over 0.6', 'Over 0.7',
            'Over 0.8', 'Over 0.9', 'Over 1',
        ],
        'Gross Margin': [
            'Any', 'Positive (>0%)', 'Negative (<0%)', 'High (>50%)', 'Over 0%',
            'Over 10%', 'Over 20%', 'Over 30%', 'Over 40%', 'Over 50%',
            'Over 60%', 'Over 70%', 'Over 80%', 'Over 90%',
        ],
        'Operating Margin': [
            'Any', 'Positive (>0%)', 'Negative (<0%)', 'Very Negative (<-20%)',
            'High (>25%)', 'Over 0%', 'Over 5%', 'Over 10%', 'Over 15%',
            'Over 20%', 'Over 25%', 'Over 30%',
        ],
        'Net Profit Margin': [
            'Any', 'Positive (>0%)', 'Negative (<0%)', 'Very Negative (<-20%)',
            'High (>20%)', 'Over 0%', 'Over 5%', 'Over 10%', 'Over 15%',
            'Over 20%', 'Over 25%', 'Over 30%',
        ],
    },
    'technical': {
        '20-Day Simple Moving Average': [
            'Any', 'Price below SMA20', 'Price 10% below SMA20',
            'Price 20% below SMA20', 'Price 30% below SMA20',
            'Price 40% below SMA20', 'Price 50% below SMA20',
            'Price above SMA20', 'Price 10% above SMA20',
            'Price 20% above SMA20', 'Price 30% above SMA20',
            'Price 40% above SMA20', 'Price 50% above SMA20',
            'Price crossed SMA20', 'Price crossed SMA20 above',
            'Price crossed SMA20 below', 'SMA20 crossed SMA50',
            'SMA20 crossed SMA50 above', 'SMA20 crossed SMA50 below',
        ],
        '50-Day Simple Moving Average': [
            'Any', 'Price below SMA50', 'Price 10% below SMA50',
            'Price 20% below SMA50', 'Price 30% below SMA50',
            'Price 40% below SMA50', 'Price 50% below SMA50',
            'Price above SMA50', 'Price 10% above SMA50',
            'Price 20% above SMA50', 'Price 30% above SMA50',
            'Price 40% above SMA50', 'Price 50% above SMA50',
            'Price crossed SMA50', 'Price crossed SMA50 above',
            'Price crossed SMA50 below', 'SMA50 crossed SMA200',
            'SMA50 crossed SMA200 above', 'SMA50 crossed SMA200 below',
        ],
        '200-Day Simple Moving Average': [
            'Any', 'Price below SMA200', 'Price 10% below SMA200',
            'Price 20% below SMA200', 'Price 30% below SMA200',
            'Price 40% below SMA200', 'Price 50% below SMA200',
            'Price above SMA200', 'Price 10% above SMA200',
            'Price 20% above SMA200', 'Price 30% above SMA200',
            'Price 40% above SMA200', 'Price 50% above SMA200',
            'Price crossed SMA200', 'Price crossed SMA200 above',
            'Price crossed SMA200 below',
        ],
        'RSI (14)': [
            'Any', 'Overbought (90)', 'Overbought (80)', 'Overbought (70)',
            'Overbought (60)', 'Oversold (40)', 'Oversold (30)', 'Oversold (20)',
            'Oversold (10)', 'Not Overbought (<60)', 'Not Overbought (<50)',
            'Not Oversold (>50)', 'Not Oversold (>40)',
        ],
        'Beta': [
            'Any', 'Under 0', 'Under 0.5', 'Under 1', 'Under 1.5', 'Under 2',
            'Over 0', 'Over 0.5', 'Over 1', 'Over 1.5', 'Over 2', 'Over 2.5',
            'Over 3', 'Over 4',
        ],
        'Volatility': [
            'Any', 'Week - Over 3%', 'Week - Over 4%', 'Week - Over 5%',
            'Week - Over 6%', 'Week - Over 7%', 'Week - Over 8%',
            'Week - Over 9%', 'Week - Over 10%', 'Week - Over 12%',
            'Week - Over 15%', 'Month - Over 2%', 'Month - Over 3%',
            'Month - Over 4%', 'Month - Over 5%', 'Month - Over 6%',
            'Month - Over 8%', 'Month - Over 10%',
        ],
        'Gap': [
            'Any', 'Up', 'Up 0%', 'Up 1%', 'Up 2%', 'Up 3%', 'Up 4%', 'Up 5%',
            'Down', 'Down 0%', 'Down 1%', 'Down 2%', 'Down 3%', 'Down 4%',
            'Down 5%',
        ],
        '52W High/Low': [
            'Any', 'New High', 'New Low', '0-3% below High', '0-5% below High',
            '0-10% below High', '5-10% below High', '10-15% below High',
            '15-20% below High', '20-30% below High', '30-40% below High',
            '40-50% below High', '50%+ below High', '0-3% above Low',
            '0-5% above Low', '0-10% above Low', '5-10% above Low',
            '10-15% above Low', '15-20% above Low', '20-30% above Low',
            '30-40% above Low', '40-50% above Low', '50%+ above Low',
        ],
        'Pattern': [
            'Any', 'Horizontal S/R', 'Horizontal S/R (Strong)', 'TL Resistance',
            'TL Resistance (Strong)', 'TL Support', 'TL Support (Strong)',
            'Wedge Up', 'Wedge Up (Strong)', 'Wedge Down', 'Wedge Down (Strong)',
            'Triangle Ascending', 'Triangle Ascending (Strong)',
            'Triangle Descending', 'Triangle Descending (Strong)', 'Wedge',
            'Wedge (Strong)', 'Channel Up', 'Channel Up (Strong)',
            'Channel Down', 'Channel Down (Strong)', 'Channel',
            'Channel (Strong)', 'Double Top', 'Double Bottom', 'Multiple Top',
            'Multiple Bottom', 'Head & Shoulders', 'Head & Shoulders Inverse',
        ],
    },
}


# ============================================================================
# HELPER: Input Validation
# ============================================================================

def _validate_profile_type(value, default='balanced'):
    """Validate and sanitize profile type input."""
    value = str(value).strip().lower()
    if value in VALID_PROFILE_TYPES:
        return value
    logger.warning("Invalid profile_type received: %s, defaulting to %s", value, default)
    return default


def _validate_budget(value, default=10000.0):
    """Validate and sanitize budget input."""
    try:
        budget = float(value)
        if math.isnan(budget) or math.isinf(budget):
            logger.warning("Invalid budget value (nan/inf): %s, defaulting to %.2f", value, default)
            return default
        if budget < MIN_BUDGET:
            logger.warning("Budget too low: %.2f, setting to minimum %.2f", budget, MIN_BUDGET)
            return MIN_BUDGET
        if budget > MAX_BUDGET:
            logger.warning("Budget too high: %.2f, capping at %.2f", budget, MAX_BUDGET)
            return MAX_BUDGET
        return budget
    except (ValueError, TypeError):
        logger.warning("Invalid budget value: %s, defaulting to %.2f", value, default)
        return default


def _sanitize_name(value, max_length=MAX_PORTFOLIO_NAME_LENGTH):
    """Sanitize a name input - strip whitespace, remove control chars, enforce length."""
    if not value:
        return ''
    cleaned = str(value).strip()
    # Remove control characters and null bytes
    cleaned = re.sub(r'[\x00-\x1f\x7f]', '', cleaned)
    return cleaned[:max_length]


# ============================================================================
# AUTHENTICATION & USER MANAGEMENT
# ============================================================================

@login_required
def home(request):
    """Dashboard with portfolio performance summary."""
    performance_data = []
    total_balance = 0.0
    total_profit_loss = 0.0
    total_daily_pl = 0.0

    try:
        portfolios = SavedPortfolio.objects.filter(user=request.user).order_by('-created_at')
        performance_data = get_portfolio_performance(portfolios)

        for item in performance_data:
            total_balance += item['current_value']
            total_profit_loss += item['profit_loss']
            total_daily_pl += item.get('total_daily_pl', 0.0)
    except Exception:
        logger.exception("Error loading portfolio performance for user %s", request.user.username)
        messages.error(request, "Could not load portfolio data. Please try again.")

    context = {
        'performance_data': performance_data,
        'total_balance': total_balance,
        'total_profit_loss': total_profit_loss,
        'total_daily_pl': total_daily_pl,
    }
    return render(request, 'SmartVest/home.html', context)


def register(request):
    """Legacy register view — redirects to allauth signup."""
    return redirect('account_signup')


@login_required
def profile(request):
    """View/edit user profile."""
    # Ensure profile exists (fallback for superusers created via CLI)
    if not hasattr(request.user, 'userprofile'):
        UserProfile.objects.create(user=request.user)

    if request.method == 'POST':
        u_form = UserUpdateForm(request.POST, instance=request.user)
        p_form = UserProfileForm(request.POST, request.FILES, instance=request.user.userprofile)
        if u_form.is_valid() and p_form.is_valid():
            u_form.save()
            p_form.save()
            logger.info("Profile updated for user: %s", request.user.username)
            messages.success(request, 'Your account has been updated!')
            return redirect('profile')
    else:
        u_form = UserUpdateForm(instance=request.user)
        p_form = UserProfileForm(instance=request.user.userprofile)

    context = {'u_form': u_form, 'p_form': p_form}
    return render(request, 'SmartVest/profile.html', context)


@login_required
def delete_profile(request):
    """Delete user account. Shows confirmation on GET, deletes on POST."""
    if request.method == 'POST':
        user = request.user
        username = user.username
        logger.info("User account deleted: %s", username)
        user.delete()
        messages.success(request, f'The profile "{username}" has been successfully deleted.')
        return redirect('account_login')

    return render(request, 'SmartVest/profile_confirm_delete.html')


# ============================================================================
# PORTFOLIO MANAGEMENT (CBVs)
# ============================================================================

class PortfolioListView(LoginRequiredMixin, ListView):
    model = SavedPortfolio
    template_name = 'SmartVest/portfolio_list.html'
    context_object_name = 'portfolios'
    ordering = ['-created_at']
    paginate_by = 12  # Tier 2: paginate to limit yfinance calls per page

    def get_queryset(self):
        return SavedPortfolio.objects.filter(user=self.request.user).order_by('-created_at')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        try:
            # Only fetch prices for the current page's portfolios (not all)
            page_portfolios = context['portfolios']
            context['performance_data'] = get_portfolio_performance(page_portfolios)
        except Exception:
            logger.exception("Error loading portfolio performance in list view")
            context['performance_data'] = []
        return context


class PortfolioDetailView(LoginRequiredMixin, UserPassesTestMixin, DetailView):
    model = SavedPortfolio
    template_name = 'SmartVest/portfolio_detail.html'

    def test_func(self):
        portfolio = self.get_object()
        return self.request.user == portfolio.user

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        try:
            portfolio = self.get_object()
            perf = get_portfolio_performance([portfolio])
            if perf:
                context['perf'] = perf[0]
        except Exception:
            logger.exception("Error loading portfolio detail performance")
        return context


class PortfolioDeleteView(LoginRequiredMixin, UserPassesTestMixin, DeleteView):
    model = SavedPortfolio
    template_name = 'SmartVest/portfolio_confirm_delete.html'
    success_url = reverse_lazy('portfolio-list')

    def test_func(self):
        portfolio = self.get_object()
        return self.request.user == portfolio.user


@login_required
@require_POST
def rename_portfolio(request, pk):
    """Rename a portfolio via AJAX POST."""
    portfolio = get_object_or_404(SavedPortfolio, pk=pk, user=request.user)
    new_name = _sanitize_name(request.POST.get('name', ''))
    if not new_name:
        return JsonResponse({'success': False, 'message': 'Name cannot be empty.'}, status=400)

    portfolio.name = new_name
    portfolio.save(update_fields=['name', 'updated_at'])
    logger.info("Portfolio %d renamed to '%s' by user %s", pk, new_name, request.user.username)
    return JsonResponse({'success': True, 'name': new_name})


# ============================================================================
# ALGORITHM INTEGRATION
# ============================================================================

def _run_algo_script(profile_type='balanced', budget=10000.0):
    """Execute selection algorithm in background thread."""
    _set_algo_running(True)
    logger.info("Starting algorithm: profile=%s, budget=%.2f", profile_type, budget)
    try:
        script_path = os.path.join(settings.BASE_DIR, 'selection_algorithm.py')
        if not os.path.isfile(script_path):
            logger.error("Selection algorithm script not found: %s", script_path)
            return

        command = [
            sys.executable, script_path,
            "--profile", str(profile_type),
            "--budget", str(budget),
        ]
        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"
        result = subprocess.run(
            command, cwd=str(settings.BASE_DIR),
            capture_output=True, text=True, timeout=600,  # 10 min timeout
            encoding='utf-8', env=env,
        )
        if result.returncode != 0:
            logger.error("Algorithm failed (exit %d): %s", result.returncode, result.stderr[:500])
        else:
            logger.info("Algorithm completed successfully.")
    except subprocess.TimeoutExpired:
        logger.error("Algorithm timed out after 600 seconds.")
    except Exception:
        logger.exception("Algorithm execution error")
    finally:
        _set_algo_running(False)


def _run_algo_script_custom(filters_dict, budget=10000.0):
    """Run algorithm with custom filters in background thread."""
    _set_algo_running(True)
    logger.info("Starting algorithm with custom filters, budget=%.2f", budget)
    temp_fd = None
    temp_filters_path = None
    try:
        script_path = os.path.join(settings.BASE_DIR, 'selection_algorithm.py')
        if not os.path.isfile(script_path):
            logger.error("Selection algorithm script not found: %s", script_path)
            return

        # Save filters to a unique temp file (prevents race conditions)
        temp_fd, temp_filters_path = tempfile.mkstemp(
            suffix='.json', prefix='smartvest_filters_', dir=str(settings.BASE_DIR)
        )
        with os.fdopen(temp_fd, 'w', encoding='utf-8') as f:
            json.dump(filters_dict, f)
        temp_fd = None  # Closed by os.fdopen

        command = [
            sys.executable, script_path,
            "--custom-filters-file", temp_filters_path,
            "--budget", str(budget),
        ]
        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"
        result = subprocess.run(
            command, cwd=str(settings.BASE_DIR),
            capture_output=True, text=True, timeout=600,
            encoding='utf-8', env=env,
        )
        if result.returncode != 0:
            logger.error("Custom algorithm failed (exit %d): %s", result.returncode, result.stderr[:500])
        else:
            logger.info("Custom algorithm completed successfully.")

    except subprocess.TimeoutExpired:
        logger.error("Custom algorithm timed out after 600 seconds.")
    except Exception:
        logger.exception("Custom algorithm execution error")
    finally:
        # Cleanup temp file
        if temp_filters_path:
            try:
                os.remove(temp_filters_path)
            except OSError:
                pass
        _set_algo_running(False)


@login_required
@require_http_methods(["GET", "POST"])
def run_analysis(request):
    """Start a new stock selection analysis."""
    algo_running = _get_algo_running()
    initial_type = _validate_profile_type(request.GET.get('type', 'balanced'))

    if request.method == 'POST':
        if algo_running:
            messages.warning(request, "Analysis is already running! Please wait.")
        else:
            profile_type = _validate_profile_type(request.POST.get('portfolio_type', 'balanced'))
            budget = _validate_budget(request.POST.get('investment_amount', 10000))

            thread = threading.Thread(
                target=_run_algo_script,
                args=(profile_type, budget),
                daemon=True,
            )
            thread.start()
            messages.success(
                request,
                f"Analysis started with {profile_type.title()} profile and ${budget:,.2f} budget. "
                f"This may take a few minutes."
            )

        return redirect('analysis-status')

    return render(request, 'SmartVest/run_analysis.html', {
        'running': algo_running,
        'initial_type': initial_type,
    })


@login_required
def select_portfolio_type(request):
    """Choose portfolio type page."""
    return render(request, 'SmartVest/portfolio_type_selection.html')


@login_required
def analysis_status(request):
    """Display analysis progress."""
    return render(request, 'SmartVest/analysis_status.html', {
        'running': _get_algo_running(),
    })


@login_required
def view_results(request):
    """Display algorithm results from CSV."""
    results_path = os.path.join(settings.BASE_DIR, 'alocare_finala_portofoliu.csv')
    results_data = []

    if os.path.exists(results_path):
        try:
            df = pd.read_csv(results_path)
            df.columns = [
                c.replace(' ', '_').replace('($)', 'USD').replace('(', '').replace(')', '')
                for c in df.columns
            ]
            results_data = df.to_dict('records')
        except Exception:
            logger.exception("Error reading results CSV: %s", results_path)

    context = {
        'results': results_data,
        'has_results': len(results_data) > 0,
    }
    return render(request, 'SmartVest/results.html', context)


@login_required
@require_POST
def save_portfolio(request):
    """Save algorithm results as a portfolio."""
    name = _sanitize_name(request.POST.get('portfolio_name'))
    description = request.POST.get('portfolio_description', '').strip()[:500]

    if not name:
        messages.error(request, "Portfolio name cannot be empty.")
        return redirect('view-results')

    # Load current results from CSV
    results_path = os.path.join(settings.BASE_DIR, 'alocare_finala_portofoliu.csv')
    portfolio_data = []

    if os.path.exists(results_path):
        try:
            df = pd.read_csv(results_path)
            df.columns = [
                c.replace(' ', '_').replace('($)', 'USD').replace('(', '').replace(')', '')
                for c in df.columns
            ]
            portfolio_data = df.to_dict('records')
        except Exception:
            logger.exception("Error reading CSV for saving")
            messages.error(request, "Failed to read portfolio data.")
            return redirect('view-results')
    else:
        messages.error(request, "No portfolio results found to save.")
        return redirect('view-results')

    if portfolio_data:
        SavedPortfolio.objects.create(
            user=request.user,
            name=name,
            description=description,
            portfolio_data=portfolio_data,
        )
        logger.info("Portfolio '%s' saved by user %s", name, request.user.username)
        messages.success(request, f"Portfolio '{name}' saved successfully!")
        return redirect('portfolio-list')

    messages.error(request, "No data to save.")
    return redirect('view-results')


@login_required
def track_performance(request):
    """Track portfolio performance with live prices."""
    try:
        portfolios = SavedPortfolio.objects.filter(user=request.user)
        performance_data = get_portfolio_performance(portfolios)
    except Exception:
        logger.exception("Error tracking performance for user %s", request.user.username)
        performance_data = []
        messages.error(request, "Could not load performance data.")

    return render(request, 'SmartVest/portfolio_performance.html', {
        'performance_data': performance_data,
    })


# ============================================================================
# MARKET NEWS
# ============================================================================

GNEWS_CACHE_KEY = "smartvest_gnews"
GNEWS_CACHE_TTL = 600  # 10 minutes — news doesn't change that fast

# Mapping of common tickers to their full company names for better news search
TICKER_TO_COMPANY = {
    'AAPL': 'Apple', 'MSFT': 'Microsoft', 'GOOGL': 'Google', 'GOOG': 'Google',
    'AMZN': 'Amazon', 'META': 'Meta', 'TSLA': 'Tesla', 'NVDA': 'Nvidia',
    'NFLX': 'Netflix', 'AMD': 'AMD', 'INTC': 'Intel', 'CRM': 'Salesforce',
    'ORCL': 'Oracle', 'ADBE': 'Adobe', 'PYPL': 'PayPal', 'DIS': 'Disney',
    'BA': 'Boeing', 'JPM': 'JPMorgan', 'V': 'Visa', 'MA': 'Mastercard',
    'WMT': 'Walmart', 'JNJ': 'Johnson & Johnson', 'PG': 'Procter & Gamble',
    'UNH': 'UnitedHealth', 'HD': 'Home Depot', 'KO': 'Coca-Cola',
    'PEP': 'PepsiCo', 'MRK': 'Merck', 'ABBV': 'AbbVie', 'AVGO': 'Broadcom',
    'COST': 'Costco', 'TMO': 'Thermo Fisher', 'MCD': "McDonald's",
    'ACN': 'Accenture', 'LIN': 'Linde', 'CSCO': 'Cisco', 'TXN': 'Texas Instruments',
    'QCOM': 'Qualcomm', 'IBM': 'IBM', 'GE': 'General Electric', 'CAT': 'Caterpillar',
    'UBER': 'Uber', 'COIN': 'Coinbase', 'SQ': 'Block', 'SHOP': 'Shopify',
    'SNAP': 'Snap', 'PLTR': 'Palantir', 'RIVN': 'Rivian', 'LCID': 'Lucid',
    'F': 'Ford', 'GM': 'General Motors', 'T': 'AT&T', 'VZ': 'Verizon',
    'XOM': 'Exxon Mobil', 'CVX': 'Chevron', 'COP': 'ConocoPhillips',
}


def _get_user_tickers(user):
    """Extract unique tickers from all of a user's saved portfolios."""
    tickers = set()
    for portfolio in SavedPortfolio.objects.filter(user=user):
        data = portfolio.portfolio_data
        if isinstance(data, list):
            for holding in data:
                ticker = holding.get('Ticker') or holding.get('ticker')
                if ticker:
                    tickers.add(ticker.upper())
    return tickers


NEWS_PER_PAGE = 10


def _clean_article(article):
    """Strip leading/trailing whitespace from article text fields."""
    for key in ('title', 'description'):
        if key in article and isinstance(article[key], str):
            article[key] = article[key].strip()
    return article


def _fetch_general_news():
    """Fetch general business news (cached)."""
    news_results = cache.get(GNEWS_CACHE_KEY)
    if news_results is None:
        news_results = []
        try:
            from gnews import GNews
            google_news = GNews(language='en', country='US', period='1d', max_results=10)
            raw_news = google_news.get_news_by_topic('BUSINESS')
            news_results = [
                _clean_article({k.replace(' ', '_'): v for k, v in article.items()})
                for article in raw_news
            ]
            cache.set(GNEWS_CACHE_KEY, news_results, timeout=GNEWS_CACHE_TTL)
            logger.info("GNews fetched and cached (%d articles)", len(news_results))
        except Exception:
            logger.exception("Error fetching market news")
    else:
        logger.debug("GNews cache HIT (%d articles)", len(news_results))
    return news_results


def _fetch_focused_news(tickers):
    """Fetch news for user's portfolio tickers using batched queries.

    Groups tickers into small batches and builds OR-queries so we make
    only a handful of GNews calls instead of one per ticker.
    """
    from gnews import GNews

    cache_key = "smartvest_gnews_focused_" + "_".join(sorted(tickers))
    cached = cache.get(cache_key)
    if cached is not None:
        logger.debug("Focused news cache HIT (%d articles)", len(cached))
        return cached

    # Build search terms: prefer company name, fall back to ticker
    search_names = []
    ticker_lookup = {}  # lowercase search term -> ticker
    for t in tickers:
        name = TICKER_TO_COMPANY.get(t, t)
        search_names.append(name)
        ticker_lookup[name.lower()] = t

    # Batch into groups of 5 joined with OR for a single query
    BATCH_SIZE = 5
    batches = [
        search_names[i:i + BATCH_SIZE]
        for i in range(0, len(search_names), BATCH_SIZE)
    ]

    all_articles = []
    seen_titles = set()

    for batch in batches:
        query = " OR ".join(f'"{name}"' for name in batch)
        try:
            google_news = GNews(language='en', country='US', period='1d', max_results=20)
            raw = google_news.get_news(query)
            for a in raw:
                article = _clean_article({k.replace(' ', '_'): v for k, v in a.items()})
                title = article.get('title', '')
                if title in seen_titles:
                    continue
                seen_titles.add(title)
                # Tag with matched ticker
                text = (title + ' ' + (article.get('description') or '')).lower()
                for name, ticker in ticker_lookup.items():
                    if name in text or ticker.lower() in text:
                        article['matched_ticker'] = ticker
                        break
                all_articles.append(article)
            logger.info("GNews focused batch %r: fetched %d articles", query[:60], len(raw))
        except Exception:
            logger.exception("Error fetching focused news batch")

    cache.set(cache_key, all_articles, timeout=GNEWS_CACHE_TTL)
    return all_articles


def _sort_news_by_portfolio(news_results, tickers):
    """Sort news so articles mentioning portfolio tickers appear first."""
    if not tickers:
        return news_results

    search_terms = {}
    for ticker in tickers:
        company = TICKER_TO_COMPANY.get(ticker)
        search_terms[ticker] = [ticker]
        if company:
            search_terms[ticker].append(company.lower())

    def relevance_score(article):
        text = (
            (article.get('title') or '') + ' ' + (article.get('description') or '')
        ).lower()
        score = 0
        for ticker, terms in search_terms.items():
            for term in terms:
                if term.lower() in text:
                    score += 1
                    break
        return score

    return sorted(news_results, key=relevance_score, reverse=True)


@login_required
def market_news(request):
    """Display business/finance news feed with optional focused view and pagination."""
    from django.core.paginator import Paginator

    focused = request.GET.get('focused') == '1'
    user_tickers = _get_user_tickers(request.user)

    if focused and user_tickers:
        news_results = _fetch_focused_news(user_tickers)
    else:
        news_results = _fetch_general_news()
        news_results = _sort_news_by_portfolio(news_results, user_tickers)

    logger.info("News: %d total articles, paginating %d per page",
                len(news_results), NEWS_PER_PAGE)
    paginator = Paginator(news_results, NEWS_PER_PAGE)
    page_number = request.GET.get('page', 1)
    page_obj = paginator.get_page(page_number)
    logger.info("News: page %s of %d, showing %d articles",
                page_obj.number, paginator.num_pages, len(page_obj))

    return render(request, 'SmartVest/market_news.html', {
        'news': page_obj,
        'focused': focused,
        'has_portfolios': bool(user_tickers),
    })


# ============================================================================
# ADMIN DASHBOARD
# ============================================================================

@login_required
@user_passes_test(lambda u: u.is_superuser)
def admin_dashboard(request):
    """Admin overview with statistics and user list.

    Tier 2: Replaced N+1 per-user query with a single annotated query.
    """
    from django.db.models import Count

    total_users = User.objects.count()
    total_portfolios = SavedPortfolio.objects.count()

    # Single query with annotation — eliminates N+1
    users = (
        User.objects
        .annotate(portfolio_count=Count('savedportfolio'))
        .order_by('-date_joined')
    )

    user_data = [
        {'user': u, 'portfolio_count': u.portfolio_count}
        for u in users
    ]

    context = {
        'total_users': total_users,
        'total_portfolios': total_portfolios,
        'user_data': user_data,
    }
    return render(request, 'SmartVest/admin_dashboard.html', context)


@login_required
@user_passes_test(lambda u: u.is_superuser)
def admin_user_detail(request, user_id):
    """Admin view of a specific user's portfolios and performance."""
    user = get_object_or_404(User, pk=user_id)
    try:
        portfolios = SavedPortfolio.objects.filter(user=user)
        performance_data = get_portfolio_performance(portfolios)
    except Exception:
        logger.exception("Error loading admin user detail for user_id=%d", user_id)
        performance_data = []

    context = {
        'target_user': user,
        'performance_data': performance_data,
    }
    return render(request, 'SmartVest/admin_user_detail.html', context)


# ============================================================================
# CUSTOM FILTERS & PRESETS
# ============================================================================

@login_required
def custom_filters(request):
    """Page with all Finviz filter options."""
    presets = FilterPreset.objects.filter(user=request.user)

    context = {
        'filters': FINVIZ_FILTERS,
        'presets': presets,
        'filters_json': json.dumps(FINVIZ_FILTERS),
    }
    return render(request, 'SmartVest/custom_filters.html', context)


@login_required
@require_POST
def save_preset(request):
    """Save a new filter preset via AJAX POST."""
    try:
        data = json.loads(request.body)
        name = _sanitize_name(data.get('name', 'My Preset'), max_length=MAX_PRESET_NAME_LENGTH)
        filters = data.get('filters', {})

        if not name:
            return JsonResponse({'success': False, 'message': 'Name cannot be empty.'}, status=400)

        if not isinstance(filters, dict):
            return JsonResponse({'success': False, 'message': 'Invalid filters format.'}, status=400)

        preset = FilterPreset.objects.create(
            user=request.user,
            name=name,
            filters=filters,
        )
        logger.info("Preset '%s' saved by user %s", name, request.user.username)
        return JsonResponse({
            'success': True,
            'preset_id': preset.id,
            'message': f'Preset "{name}" saved successfully!',
        })
    except json.JSONDecodeError:
        return JsonResponse({'success': False, 'message': 'Invalid JSON data.'}, status=400)
    except Exception:
        logger.exception("Error saving preset")
        return JsonResponse({'success': False, 'message': 'Server error.'}, status=500)


@login_required
@require_POST
def delete_preset(request, pk):
    """Delete a filter preset. Requires POST for safety."""
    preset = get_object_or_404(FilterPreset, pk=pk, user=request.user)
    preset_name = preset.name
    preset.delete()
    logger.info("Preset '%s' deleted by user %s", preset_name, request.user.username)
    messages.success(request, f'Preset "{preset_name}" deleted successfully!')
    return redirect('presets-list')


@login_required
def presets_list(request):
    """List all user's filter presets."""
    presets = FilterPreset.objects.filter(user=request.user)
    return render(request, 'SmartVest/presets_list.html', {'presets': presets})


@login_required
@require_POST
def update_preset(request, pk):
    """Update a filter preset's name and description. Requires POST."""
    preset = get_object_or_404(FilterPreset, pk=pk, user=request.user)

    new_name = _sanitize_name(request.POST.get('name', preset.name), max_length=MAX_PRESET_NAME_LENGTH)
    new_description = request.POST.get('description', preset.description).strip()[:500]

    if new_name:
        preset.name = new_name
    preset.description = new_description
    preset.save(update_fields=['name', 'description', 'updated_at'])
    logger.info("Preset '%s' updated by user %s", preset.name, request.user.username)
    messages.success(request, f'Preset "{preset.name}" updated successfully!')
    return redirect('presets-list')


@login_required
def run_with_preset(request, pk):
    """Run analysis with a saved preset's filters."""
    preset = get_object_or_404(FilterPreset, pk=pk, user=request.user)

    if _get_algo_running():
        messages.warning(request, "An analysis is already running!")
        return redirect('analysis-status')

    budget = _validate_budget(request.GET.get('budget', 10000))

    thread = threading.Thread(
        target=_run_algo_script_custom,
        args=(preset.filters, budget),
        daemon=True,
    )
    thread.start()

    logger.info("Analysis started with preset '%s' by user %s", preset.name, request.user.username)
    messages.success(request, f"Analysis started with preset '{preset.name}' and budget ${budget:,.2f}.")
    return redirect('analysis-status')


def get_user_presets(request):
    """Get presets for sidebar - returns as context."""
    if request.user.is_authenticated:
        return FilterPreset.objects.filter(user=request.user)[:5]
    return []


# ============================================================================
# UNICORN SCANNER
# ============================================================================

@login_required
def unicorn_scanner(request):
    """Main unicorn scanner page - two-step UX with relax option."""
    scan_results = []
    error_message = None
    is_scanning = False
    show_relax_prompt = False
    is_relaxed = False
    has_perfect_results = False

    # Fields we actually need in session — drop everything else to save memory
    _UNICORN_KEEP_FIELDS = {
        'Ticker', 'Company', 'Price', 'Sector', 'Industry',
        'RSI', 'Volume_Ratio', 'Pct_of_52W', 'Unicorn_Score',
    }

    if request.method == 'POST':
        if 'run_scan' in request.POST:
            # --- FRESH SCAN ---
            try:
                from unicorn_scanner import scan_for_unicorns

                is_scanning = True
                df_all_scored, _ = scan_for_unicorns()

                if not df_all_scored.empty:
                    # Tier 2: Only keep essential fields to reduce session size
                    raw_results = df_all_scored.to_dict('records')
                    all_results = [
                        {k: v for k, v in row.items() if k in _UNICORN_KEEP_FIELDS}
                        for row in raw_results
                    ]
                    request.session['unicorn_all_results'] = all_results
                    request.session.modified = True

                    perfect = [r for r in all_results if r.get('Unicorn_Score', 0) >= 3]

                    if perfect:
                        scan_results = perfect
                        has_perfect_results = True
                        show_relax_prompt = True
                    else:
                        strong = [r for r in all_results if r.get('Unicorn_Score', 0) >= 2]
                        if strong:
                            show_relax_prompt = True
                            error_message = (
                                f"Nu am gasit companii cu scor perfect (3/3), "
                                f"dar exista {len(strong)} companii cu scor 2/3."
                            )
                        else:
                            error_message = "Nu s-au gasit candidati unicorn. Incearca din nou mai tarziu."
                else:
                    error_message = "Scanarea nu a returnat rezultate. Incearca din nou mai tarziu."
            except Exception:
                logger.exception("Unicorn scan error")
                error_message = "Eroare la scanare. Incearca din nou mai tarziu."

        elif 'relax_filters' in request.POST:
            # --- RELAX: show 2/3 from cached data ---
            all_results = request.session.get('unicorn_all_results', [])
            if all_results:
                scan_results = [r for r in all_results if r.get('Unicorn_Score', 0) >= 2]
                is_relaxed = True
                has_perfect_results = any(r.get('Unicorn_Score', 0) >= 3 for r in scan_results)
            else:
                error_message = "Nu exista rezultate anterioare. Ruleaza o scanare noua."
    else:
        # GET request - check for cached results
        all_results = request.session.get('unicorn_all_results', [])
        if all_results:
            perfect = [r for r in all_results if r.get('Unicorn_Score', 0) >= 3]
            if perfect:
                scan_results = perfect
                has_perfect_results = True
                show_relax_prompt = True
            else:
                strong = [r for r in all_results if r.get('Unicorn_Score', 0) >= 2]
                if strong:
                    show_relax_prompt = True

    # Store filtered results for watchlist add
    if scan_results:
        request.session['unicorn_results'] = scan_results
        request.session.modified = True

    # Get user's watchlist with live prices
    watchlist = WatchedUnicorn.objects.filter(user=request.user)
    watched_tickers = [w.ticker for w in watchlist]
    watchlist_with_pl = _build_watchlist_with_pl(watchlist)

    context = {
        'scan_results': scan_results,
        'watchlist': watchlist_with_pl,
        'watched_tickers': watched_tickers,
        'error_message': error_message,
        'is_scanning': is_scanning,
        'show_relax_prompt': show_relax_prompt,
        'is_relaxed': is_relaxed,
        'has_perfect_results': has_perfect_results,
    }
    return render(request, 'SmartVest/unicorn_scanner.html', context)


def _build_watchlist_with_pl(watchlist):
    """Build watchlist data with real-time P/L calculations.

    Tier 2: Uses fetch_prices_cached() so the watchlist shares the
    same price cache as portfolio performance — no duplicate downloads.
    """
    watchlist_with_pl = []
    if not watchlist:
        return watchlist_with_pl

    tickers_to_fetch = set(w.ticker for w in watchlist if w.entry_price)

    # Use the shared cached price fetcher
    current_prices, prev_closes = fetch_prices_cached(tickers_to_fetch)

    for w in watchlist:
        entry_price = float(w.entry_price) if w.entry_price else None
        curr_price = current_prices.get(w.ticker)
        prev_close = prev_closes.get(w.ticker)

        item = {
            'pk': w.pk,
            'ticker': w.ticker,
            'company_name': w.company_name,
            'entry_price': entry_price,
            'added_at': w.added_at,
            'notes': w.notes,
            'current_price': round(curr_price, 2) if curr_price else None,
            'daily_pl': None,
            'daily_pl_pct': None,
            'open_pl': None,
            'open_pl_pct': None,
        }

        if curr_price and prev_close:
            daily_pl = curr_price - prev_close
            item['daily_pl'] = round(daily_pl, 2)
            item['daily_pl_pct'] = round((daily_pl / prev_close) * 100, 2) if prev_close else 0

        if curr_price and entry_price and entry_price > 0:
            open_pl = curr_price - entry_price
            item['open_pl'] = round(open_pl, 2)
            item['open_pl_pct'] = round((open_pl / entry_price) * 100, 2)

        watchlist_with_pl.append(item)

    return watchlist_with_pl


@login_required
def unicorn_watchlist(request):
    """Dedicated watchlist page with full data including sector/industry."""
    watched = WatchedUnicorn.objects.filter(user=request.user).order_by('-added_at')
    watchlist = _build_watchlist_with_pl(watched)

    # Fetch sector/industry info via yfinance for all watched tickers
    tickers = [w.ticker for w in watched if w.ticker]
    if tickers:
        try:
            import yfinance as yf
            ticker_objects = yf.Tickers(' '.join(tickers))
            info_map = {}
            for t in tickers:
                try:
                    info = ticker_objects.tickers[t].info
                    info_map[t] = {
                        'sector': info.get('sector', ''),
                        'industry': info.get('industry', ''),
                        'quote_type': info.get('quoteType', ''),
                    }
                except Exception:
                    info_map[t] = {'sector': '', 'industry': '', 'quote_type': ''}
            # Merge into watchlist items
            for item in watchlist:
                extra = info_map.get(item['ticker'], {})
                item['sector'] = extra.get('sector', '')
                item['industry'] = extra.get('industry', '')
                item['quote_type'] = extra.get('quote_type', '')
        except Exception as e:
            logger.warning("Failed to fetch yfinance info for watchlist: %s", e)
            for item in watchlist:
                item['sector'] = ''
                item['industry'] = ''
                item['quote_type'] = ''

    return render(request, 'SmartVest/unicorn_watchlist.html', {
        'watchlist': watchlist,
    })


@login_required
@require_POST
def add_to_watchlist(request, ticker):
    """Add a stock to user's unicorn watchlist. Requires POST."""
    # Basic ticker validation
    ticker = str(ticker).upper().strip()[:10]
    if not ticker.isalpha():
        messages.error(request, "Invalid ticker symbol.")
        return redirect('unicorn-scanner')

    scan_results = request.session.get('unicorn_results', [])
    stock_info = next((s for s in scan_results if s.get('Ticker') == ticker), None)

    if WatchedUnicorn.objects.filter(user=request.user, ticker=ticker).exists():
        messages.warning(request, f'{ticker} is already in your watchlist!')
    else:
        WatchedUnicorn.objects.create(
            user=request.user,
            ticker=ticker,
            company_name=stock_info.get('Company', '') if stock_info else '',
            entry_price=stock_info.get('Price') if stock_info else None,
        )
        logger.info("User %s added %s to watchlist", request.user.username, ticker)
        messages.success(request, f'{ticker} has been added to your watchlist!')

    return redirect('unicorn-scanner')


@login_required
@require_POST
def remove_from_watchlist(request, pk):
    """Remove a stock from user's unicorn watchlist. Requires POST."""
    watched = get_object_or_404(WatchedUnicorn, pk=pk, user=request.user)
    ticker = watched.ticker
    watched.delete()
    logger.info("User %s removed %s from watchlist", request.user.username, ticker)
    messages.success(request, f'{ticker} has been removed from your watchlist.')
    return redirect('unicorn-scanner')


# ============================================================================
# BACKTESTING (ADMIN-ONLY)
# ============================================================================

def _backtest_progress_callback(message, percent):
    """Called by BacktestEngine to report progress (thread-safe via cache)."""
    progress = _get_backtest_progress()
    progress['percent'] = percent
    progress['message'] = message
    _set_backtest_progress(progress)


def _run_backtest_thread(start_date, end_date, profile_type, initial_capital):
    """Run backtest in background thread (thread-safe via cache)."""
    progress = {
        'running': True,
        'result': None,
        'percent': 0,
        'message': 'Initializing...',
    }
    _set_backtest_progress(progress)

    try:
        from backtester import BacktestEngine

        engine = BacktestEngine(
            start_date=start_date,
            end_date=end_date,
            profile_type=profile_type,
            initial_capital=initial_capital,
            rebalance_months=3,
            progress_callback=_backtest_progress_callback,
        )

        result = engine.run()

        progress = _get_backtest_progress()
        progress['result'] = result.to_dict()
        progress['percent'] = 100
        progress['message'] = 'Backtest finalizat!'
        progress['running'] = False
        _set_backtest_progress(progress)

        logger.info("Backtest completed: %s, %s to %s", profile_type, start_date, end_date)

    except Exception as e:
        logger.exception("Backtest error")
        progress = _get_backtest_progress()
        progress['result'] = {
            'metrics': {'error': str(e)},
            'profile_type': profile_type,
            'start_date': start_date,
            'end_date': end_date,
            'initial_capital': initial_capital,
            'equity_curve': {'dates': [], 'values': []},
            'benchmark_curve': {'dates': [], 'values': []},
            'snapshots': [],
        }
        progress['percent'] = 100
        progress['message'] = f'Eroare: {str(e)}'
        progress['running'] = False
        _set_backtest_progress(progress)


@login_required
@user_passes_test(lambda u: u.is_superuser)
@require_http_methods(["GET", "POST"])
def backtest_view(request):
    """Main backtesting page - admin only."""
    bt_progress = _get_backtest_progress()
    result = None

    if request.method == 'POST':
        if bt_progress.get('running'):
            messages.warning(request, "A backtest is already running!")
            return redirect('backtest')

        # Validate inputs
        try:
            period_years = int(request.POST.get('period', 2))
            if period_years < 1 or period_years > 10:
                period_years = 2
        except (ValueError, TypeError):
            period_years = 2

        profile_type = _validate_profile_type(request.POST.get('profile_type', 'balanced'))
        initial_capital = _validate_budget(request.POST.get('initial_capital', 10000))

        # Calculate dates
        end_date = datetime.date.today().strftime('%Y-%m-%d')
        start_date = (
            datetime.date.today() - datetime.timedelta(days=period_years * 365)
        ).strftime('%Y-%m-%d')

        thread = threading.Thread(
            target=_run_backtest_thread,
            args=(start_date, end_date, profile_type, initial_capital),
            daemon=True,
        )
        thread.start()

        logger.info(
            "Backtest started: %s, %dY, $%.0f by superuser %s",
            profile_type, period_years, initial_capital, request.user.username,
        )
        messages.success(
            request,
            f"Backtest started: {profile_type.title()}, {period_years}Y, ${initial_capital:,.0f}",
        )
        return redirect('backtest')

    if bt_progress.get('result'):
        result = bt_progress['result']
        if result.get('snapshots'):
            for snap in result['snapshots']:
                if snap.get('allocations'):
                    first_val = next(iter(snap['allocations'].values()), 0)
                    if first_val <= 1:
                        snap['allocations'] = {
                            k: round(v * 100, 1)
                            for k, v in snap['allocations'].items()
                            if v > 0
                        }

    context = {
        'result': result,
        'running': bt_progress.get('running', False),
    }
    return render(request, 'SmartVest/backtest.html', context)


@login_required
@user_passes_test(lambda u: u.is_superuser)
def backtest_progress_api(request):
    """AJAX endpoint for polling backtest progress."""
    bt_progress = _get_backtest_progress()
    return JsonResponse({
        'percent': bt_progress.get('percent', 0),
        'message': bt_progress.get('message', 'Idle'),
        'running': bt_progress.get('running', False),
    })


@login_required
@user_passes_test(lambda u: u.is_superuser)
def backtest_results(request):
    """Admin-only page showing all automated backtest results."""
    from django.db.models import Avg, Count, Max, Min

    # Filter by profile if requested
    profile_filter = request.GET.get('profile', '')
    if profile_filter and profile_filter not in VALID_PROFILE_TYPES:
        profile_filter = ''

    runs = BacktestRun.objects.filter(status='done')
    if profile_filter:
        runs = runs.filter(profile_type=profile_filter)

    # Summary stats
    stats = runs.aggregate(
        count=Count('id'),
        avg_return=Avg('total_return'),
        avg_sharpe=Avg('sharpe_ratio'),
        avg_drawdown=Avg('max_drawdown'),
        avg_volatility=Avg('annual_volatility'),
        avg_alpha=Avg('alpha'),
        best_return=Max('total_return'),
        worst_return=Min('total_return'),
    )

    # Win rate
    total_done = runs.count()
    wins = runs.filter(total_return__gt=0).count()
    win_rate = (wins / total_done * 100) if total_done > 0 else 0

    # Beat SPY rate
    beat_spy = runs.filter(outperformance__gt=0).count()
    beat_spy_rate = (beat_spy / total_done * 100) if total_done > 0 else 0

    # Per-profile breakdown
    profile_stats = {}
    for p in VALID_PROFILE_TYPES:
        p_runs = BacktestRun.objects.filter(status='done', profile_type=p)
        p_count = p_runs.count()
        if p_count > 0:
            p_agg = p_runs.aggregate(
                avg_return=Avg('total_return'),
                avg_sharpe=Avg('sharpe_ratio'),
                avg_drawdown=Avg('max_drawdown'),
                wins=Count('id', filter=db_models.Q(total_return__gt=0)),
            )
            profile_stats[p] = {
                'count': p_count,
                'avg_return': p_agg['avg_return'],
                'avg_sharpe': p_agg['avg_sharpe'],
                'avg_drawdown': p_agg['avg_drawdown'],
                'win_rate': (p_agg['wins'] / p_count * 100) if p_count > 0 else 0,
            }

    # Sorting with whitelist
    sort_by = request.GET.get('sort', '-created_at')
    allowed_sorts = [
        'name', '-name', 'total_return', '-total_return',
        'sharpe_ratio', '-sharpe_ratio', 'max_drawdown', '-max_drawdown',
        'created_at', '-created_at', 'start_date', '-start_date',
        'cagr', '-cagr', 'alpha', '-alpha',
    ]
    if sort_by not in allowed_sorts:
        sort_by = '-created_at'
    runs = runs.order_by(sort_by)

    context = {
        'runs': runs,
        'stats': stats,
        'win_rate': round(win_rate, 1),
        'beat_spy_rate': round(beat_spy_rate, 1),
        'profile_stats': profile_stats,
        'current_profile': profile_filter,
        'current_sort': sort_by,
        'total_failed': BacktestRun.objects.filter(status='failed').count(),
        'total_running': BacktestRun.objects.filter(status='running').count(),
    }
    return render(request, 'SmartVest/backtest_results.html', context)


@login_required
@user_passes_test(lambda u: u.is_superuser)
def backtest_result_detail(request, pk):
    """Detail view for a single backtest run."""
    run = get_object_or_404(BacktestRun, pk=pk)

    equity_curve = run.equity_curve_json or {}
    benchmark_curve = run.benchmark_curve_json or {}
    snapshots = run.snapshots_json or []

    result = {
        'profile_type': run.profile_type,
        'start_date': str(run.start_date),
        'end_date': str(run.end_date),
        'metrics': {
            'total_return': run.total_return,
            'cagr': run.cagr,
            'sharpe_ratio': run.sharpe_ratio,
            'sortino_ratio': run.sortino_ratio,
            'max_drawdown': run.max_drawdown,
            'max_drawdown_duration': run.max_drawdown_duration,
            'calmar_ratio': run.calmar_ratio,
            'annual_volatility': run.annual_volatility,
            'alpha': run.alpha,
            'beta': run.beta,
            'benchmark_return': run.benchmark_return,
            'outperformance': run.outperformance,
            'final_value': run.final_value,
            'n_trading_days': run.n_trading_days,
        },
        'equity_curve': equity_curve,
        'benchmark_curve': benchmark_curve,
        'snapshots': snapshots,
    }

    context = {
        'run': run,
        'result': result,
        'equity_dates_json': json.dumps(equity_curve.get('dates', [])),
        'equity_values_json': json.dumps(equity_curve.get('values', [])),
        'benchmark_values_json': json.dumps(benchmark_curve.get('values', [])),
        'has_benchmark': bool(benchmark_curve.get('dates')),
    }
    return render(request, 'SmartVest/backtest_result_detail.html', context)


@login_required
@user_passes_test(lambda u: u.is_superuser)
def backtest_runner_status(request):
    """AJAX endpoint: returns current status of the automated runner."""
    running = BacktestRun.objects.filter(status='running').first()
    done_count = BacktestRun.objects.filter(status='done').count()

    if running:
        return JsonResponse({
            'running': True,
            'name': running.name,
            'profile': running.profile_type,
            'start_date': str(running.start_date),
            'end_date': str(running.end_date),
            'done_count': done_count,
        })
    return JsonResponse({
        'running': False,
        'done_count': done_count,
    })


# ============================================================================
# NOTIFICATIONS
# ============================================================================

@login_required
def notifications_list(request):
    """Return recent notifications as JSON for the bell dropdown."""
    notifications = Notification.objects.filter(user=request.user)[:20]
    data = [{
        'id': n.id,
        'type': n.notification_type,
        'title': n.title,
        'message': n.message,
        'link': n.link,
        'is_read': n.is_read,
        'created_at': n.created_at.strftime('%b %d, %H:%M'),
    } for n in notifications]
    unread = Notification.objects.filter(user=request.user, is_read=False).count()
    return JsonResponse({'notifications': data, 'unread_count': unread})


@login_required
@require_POST
def notifications_mark_read(request):
    """Mark all notifications as read."""
    Notification.objects.filter(user=request.user, is_read=False).update(is_read=True)
    return JsonResponse({'success': True})


@login_required
@require_POST
def notification_mark_read(request, pk):
    """Mark a single notification as read."""
    Notification.objects.filter(pk=pk, user=request.user).update(is_read=True)
    return JsonResponse({'success': True})


@login_required
def notification_preferences(request):
    """View/edit notification preferences."""
    prefs, _ = NotificationPreference.objects.get_or_create(user=request.user)
    if request.method == 'POST':
        form = NotificationPreferenceForm(request.POST, instance=prefs)
        if form.is_valid():
            form.save()
            messages.success(request, 'Notification preferences updated.')
            return redirect('notification-preferences')
    else:
        form = NotificationPreferenceForm(instance=prefs)
    return render(request, 'SmartVest/notification_preferences.html', {'form': form})


@login_required
@require_POST
def run_alert_scan(request):
    """Manually trigger all alert checks for the current user."""
    import threading
    from .tasks import check_price_alerts, check_portfolio_alerts

    def _run_checks():
        try:
            # Run price alerts (skip market-hours check for manual trigger)
            _run_price_alerts_for_user(request.user)
            # Run portfolio alerts for this user
            _run_portfolio_alerts_for_user(request.user)
        except Exception:
            logger.exception("Error in manual alert scan")

    def _run_price_alerts_for_user(user):
        """Price alert check scoped to a single user."""
        from .models import PriceAlert, WatchedUnicorn, NotificationPreference
        from .utils import fetch_prices_cached
        from .notifications import send_notification
        from datetime import date

        tickers = set()
        active_alerts = PriceAlert.objects.filter(user=user, is_triggered=False)
        watched_with_targets = WatchedUnicorn.objects.filter(user=user, target_price__isnull=False)
        all_watched = WatchedUnicorn.objects.filter(user=user, entry_price__isnull=False)

        for a in active_alerts:
            tickers.add(a.ticker)
        for w in watched_with_targets:
            tickers.add(w.ticker)
        for w in all_watched:
            tickers.add(w.ticker)

        if not tickers:
            return

        current_prices, prev_closes = fetch_prices_cached(tickers)

        # Check explicit PriceAlert targets
        triggered = []
        for alert in active_alerts:
            curr = current_prices.get(alert.ticker)
            if curr is None:
                continue
            hit = False
            if alert.direction == PriceAlert.Direction.ABOVE and curr >= float(alert.target_price):
                hit = True
            elif alert.direction == PriceAlert.Direction.BELOW and curr <= float(alert.target_price):
                hit = True
            if hit:
                alert.is_triggered = True
                alert.triggered_at = timezone.now()
                triggered.append(alert)
                direction_label = "rose above" if alert.direction == PriceAlert.Direction.ABOVE else "dropped below"
                send_notification(user, Notification.Type.PRICE_ALERT,
                    f"{alert.ticker} {direction_label} ${alert.target_price}",
                    f"{alert.ticker} is now at ${curr:.2f} (target: ${alert.target_price}).",
                    "/unicorns/watchlist/")
        if triggered:
            PriceAlert.objects.bulk_update(triggered, ['is_triggered', 'triggered_at'])

        # Check watchlist targets
        for w in watched_with_targets:
            curr = current_prices.get(w.ticker)
            if curr and curr >= float(w.target_price):
                dedup = f"sv_alert_sent_{user.id}_{w.ticker}_{date.today().isoformat()}"
                if not cache.get(dedup):
                    send_notification(user, Notification.Type.PRICE_ALERT,
                        f"{w.ticker} hit target ${float(w.target_price):.2f}",
                        f"{w.ticker} reached ${curr:.2f} (your target: ${float(w.target_price):.2f}).",
                        "/unicorns/watchlist/")
                    cache.set(dedup, True, timeout=86400)

        # Check daily % moves
        prefs, _ = NotificationPreference.objects.get_or_create(user=user)
        threshold = float(prefs.price_change_threshold)
        for w in all_watched:
            curr = current_prices.get(w.ticker)
            prev = prev_closes.get(w.ticker)
            if not curr or not prev or prev == 0:
                continue
            dedup = f"sv_alert_sent_{user.id}_{w.ticker}_{date.today().isoformat()}"
            if cache.get(dedup):
                continue
            daily_pct = abs((curr - prev) / prev) * 100
            if daily_pct >= threshold:
                direction = "up" if curr > prev else "down"
                send_notification(user, Notification.Type.PRICE_ALERT,
                    f"{w.ticker} {direction} {daily_pct:.1f}% today",
                    f"{w.ticker} moved from ${prev:.2f} to ${curr:.2f}.",
                    "/unicorns/watchlist/")
                cache.set(dedup, True, timeout=86400)

    def _run_portfolio_alerts_for_user(user):
        """Portfolio alert check scoped to a single user."""
        from .models import SavedPortfolio, NotificationPreference
        from .utils import get_portfolio_performance
        from .notifications import send_notification
        from datetime import date

        prefs, _ = NotificationPreference.objects.get_or_create(user=user)
        if not prefs.portfolio_alerts_enabled:
            return

        portfolios = list(SavedPortfolio.objects.filter(user=user))
        if not portfolios:
            return

        try:
            perf_data = get_portfolio_performance(portfolios)
        except Exception:
            return

        threshold = float(prefs.portfolio_drawdown_threshold)
        for perf in perf_data:
            portfolio = perf['portfolio']
            return_pct = perf['return_pct']
            if return_pct <= -threshold:
                send_notification(user, Notification.Type.PORTFOLIO_ALERT,
                    f"{portfolio.name} down {abs(return_pct):.1f}%",
                    f"Portfolio '{portfolio.name}' has lost ${abs(perf['profit_loss']):.2f} ({return_pct:.1f}%).",
                    f"/portfolios/{portfolio.pk}/")
            elif return_pct >= 20:
                send_notification(user, Notification.Type.PORTFOLIO_ALERT,
                    f"{portfolio.name} up {return_pct:.1f}%!",
                    f"Portfolio '{portfolio.name}' has gained ${perf['profit_loss']:.2f} (+{return_pct:.1f}%).",
                    f"/portfolios/{portfolio.pk}/")

    # Run in background thread so the response is instant
    threading.Thread(target=_run_checks, daemon=True).start()
    return JsonResponse({'success': True, 'message': 'Alert scan started'})


# ============================================================================
# PORTFOLIO HEALTH CHECK
# ============================================================================

@login_required
def portfolio_health(request, pk):
    """Portfolio health check page (template shell — results fetched via AJAX)."""
    portfolio = get_object_or_404(SavedPortfolio, pk=pk, user=request.user)
    return render(request, 'SmartVest/portfolio_health.html', {'portfolio': portfolio})


@login_required
def portfolio_health_api(request, pk):
    """API: Run health check analysis and return JSON."""
    portfolio = get_object_or_404(SavedPortfolio, pk=pk, user=request.user)

    # Allow cache bypass via ?refresh=1
    if request.GET.get('refresh'):
        cache.delete(f"sv_health_{portfolio.pk}")

    from .rebalance import portfolio_health_check
    results = portfolio_health_check(portfolio)
    return JsonResponse(results)


# ============================================================================
# PUSH SUBSCRIPTIONS
# ============================================================================

@login_required
@require_POST
def push_subscribe(request):
    """Save a browser push subscription for the current user."""
    try:
        data = json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        return JsonResponse({'error': 'Invalid JSON'}, status=400)

    endpoint = data.get('endpoint', '')
    keys = data.get('keys', {})
    p256dh = keys.get('p256dh', '')
    auth = keys.get('auth', '')

    if not endpoint or not p256dh or not auth:
        return JsonResponse({'error': 'Missing subscription fields'}, status=400)

    # Validate endpoint is a proper HTTPS URL
    if not endpoint.startswith('https://'):
        return JsonResponse({'error': 'Invalid push endpoint'}, status=400)

    PushSubscription.objects.update_or_create(
        endpoint=endpoint,
        defaults={
            'user': request.user,
            'p256dh': p256dh,
            'auth': auth,
        },
    )
    return JsonResponse({'success': True})


@login_required
@require_POST
def push_unsubscribe(request):
    """Remove a browser push subscription."""
    try:
        data = json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        return JsonResponse({'error': 'Invalid JSON'}, status=400)

    endpoint = data.get('endpoint', '')
    PushSubscription.objects.filter(endpoint=endpoint, user=request.user).delete()
    return JsonResponse({'success': True})
