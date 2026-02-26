from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.contrib.auth.decorators import login_required, user_passes_test
from django.http import JsonResponse
import datetime
import threading
from django.contrib.auth.models import User
from .forms import UserRegisterForm, UserProfileForm, UserUpdateForm
from django.db import models as db_models
from .models import UserProfile, SavedPortfolio, BacktestRun

@login_required
def home(request):
    performance_data = []
    total_balance = 0.0
    total_profit_loss = 0.0
    total_daily_pl = 0.0
    
    if request.user.is_authenticated:
        portfolios = SavedPortfolio.objects.filter(user=request.user).order_by('-created_at')
        performance_data = get_portfolio_performance(portfolios)
        
        for item in performance_data:
            total_balance += item['current_value']
            total_profit_loss += item['profit_loss']
            total_daily_pl += item.get('total_daily_pl', 0.0)
    
    context = {
        'performance_data': performance_data,
        'total_balance': total_balance,
        'total_profit_loss': total_profit_loss,
        'total_daily_pl': total_daily_pl,
    }
    return render(request, 'SmartVest/home.html', context)

def register(request):
    if request.method == 'POST':
        form = UserRegisterForm(request.POST)
        if form.is_valid():
            user = form.save()
            # Create a profile for the user
            UserProfile.objects.create(user=user)
            username = form.cleaned_data.get('username')
            messages.success(request, f'Account created for {username}! You can now login.')
            return redirect('login')
    else:
        form = UserRegisterForm()
    return render(request, 'SmartVest/register.html', {'form': form})

@login_required
def profile(request):
    if request.method == 'POST':
        u_form = UserUpdateForm(request.POST, instance=request.user)
        p_form = UserProfileForm(request.POST, request.FILES, instance=request.user.userprofile)
        if u_form.is_valid() and p_form.is_valid():
            u_form.save()
            p_form.save()
            messages.success(request, f'Contul tău a fost actualizat!')
            return redirect('profile')
    else:
        # Ensure profile exists (fallback for superusers created via CLI)
        if not hasattr(request.user, 'userprofile'):
            UserProfile.objects.create(user=request.user)
            
        u_form = UserUpdateForm(instance=request.user)
        p_form = UserProfileForm(instance=request.user.userprofile)

    context = {
        'u_form': u_form,
        'p_form': p_form
    }
    return render(request, 'SmartVest/profile.html', context)

@login_required
def delete_profile(request):
    if request.method == 'POST':
        user = request.user
        username = user.username
        # Delete user
        user.delete()
        messages.success(request, f'Profilul "{username}" a fost șters cu succes.')
        return redirect('login')
        
    return render(request, 'SmartVest/profile_confirm_delete.html')

from .models import SavedPortfolio
from .forms import SavedPortfolioForm
from django.shortcuts import get_object_or_404
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.views.generic import ListView, CreateView, UpdateView, DeleteView, DetailView

# Using CBVs for CRUD is cleaner standard practice in Django
class PortfolioListView(LoginRequiredMixin, ListView):
    model = SavedPortfolio
    template_name = 'SmartVest/portfolio_list.html'
    context_object_name = 'portfolios'
    ordering = ['-created_at']

    def get_queryset(self):
        return SavedPortfolio.objects.filter(user=self.request.user).order_by('-created_at')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        portfolios = self.get_queryset()
        context['performance_data'] = get_portfolio_performance(portfolios)
        return context

class PortfolioDetailView(LoginRequiredMixin, UserPassesTestMixin, DetailView):
    model = SavedPortfolio
    template_name = 'SmartVest/portfolio_detail.html'

    def test_func(self):
        portfolio = self.get_object()
        if self.request.user == portfolio.user:
            return True
        return False

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        portfolio = self.get_object()
        perf = get_portfolio_performance([portfolio])
        if perf:
            context['perf'] = perf[0]
        return context

class PortfolioDeleteView(LoginRequiredMixin, UserPassesTestMixin, DeleteView):
    model = SavedPortfolio
    template_name = 'SmartVest/portfolio_confirm_delete.html'
    success_url = '/portfolios/' # Redirecting to portfolio list after delete

    def test_func(self):
        portfolio = self.get_object()
        if self.request.user == portfolio.user:
            return True
        return False

# ==========================
# ALGORITHM INTEGRATION
# ==========================
import threading
import subprocess
import os
import pandas as pd
from django.conf import settings

# Global flag for simplicity in this demo (single instance)
ALGO_RUNNING = False

def run_algo_script(profile_type='balanced', budget=10000.0):
    global ALGO_RUNNING
    ALGO_RUNNING = True
    print(f"Starting Algorithm Script with Profile: {profile_type}, Budget: {budget}...")
    try:
        # Path to the script (Assuming it's in the project root c:\Licenta\Proiect-PWA\selection_algorithm.py)
        # settings.BASE_DIR is c:\Licenta\Proiect-PWA\finance_project\.. -> c:\Licenta\Proiect-PWA
        script_path = os.path.join(settings.BASE_DIR, 'selection_algorithm.py')
        
        # Run it with arguments
        command = ["python", script_path, "--profile", str(profile_type), "--budget", str(budget)]
        
        # capture_output=True to avoid cluttering main stdout, or False to see it in console
        subprocess.run(command, cwd=settings.BASE_DIR, check=True)
        print("Algorithm Script Finished.")
    except Exception as e:
        print(f"Algorithm Error: {e}")
    finally:
        ALGO_RUNNING = False

@login_required
def run_analysis(request):
    global ALGO_RUNNING
    
    # Defaults
    initial_type = request.GET.get('type', 'balanced')
    
    if request.method == 'POST':
        if ALGO_RUNNING:
            messages.warning(request, "Analysis is already running! Please wait.")
        else:
            profile_type = request.POST.get('portfolio_type', 'balanced')
            try:
                budget = float(request.POST.get('investment_amount', 10000))
            except ValueError:
                budget = 10000.0
                
            # Start in background thread
            thread = threading.Thread(target=run_algo_script, args=(profile_type, budget))
            thread.daemon = True
            thread.start()
            messages.success(request, f"Analysis started with {profile_type.title()} profile and ${budget:,.2f} budget. This may take a few minutes.")
            
        return redirect('analysis-status')
        
    return render(request, 'SmartVest/run_analysis.html', {'running': ALGO_RUNNING, 'initial_type': initial_type})

@login_required
def select_portfolio_type(request):
    return render(request, 'SmartVest/portfolio_type_selection.html')

@login_required
def analysis_status(request):
    return render(request, 'SmartVest/analysis_status.html', {'running': ALGO_RUNNING})

@login_required
def view_results(request):
    # Load the CSVs if they exist
    results_path = os.path.join(settings.BASE_DIR, 'alocare_finala_portofoliu.csv')
    comp_path = os.path.join(settings.BASE_DIR, 'companii_selectie_finala.csv')
    
    results_data = []
    
    # Check if results exist
    if os.path.exists(results_path):
        try:
            df = pd.read_csv(results_path)
            # Clean up column names for template access if necessary
            # e.g. "Valoare_Investitie ($)" might be hard to access in template
            df.columns = [c.replace(' ', '_').replace('($)', 'USD').replace('(', '').replace(')', '') for c in df.columns]
            results_data = df.to_dict('records')
        except Exception as e:
            print(f"Error reading CSV: {e}")
            
    context = {
        'results': results_data,
        'has_results': (len(results_data) > 0)
    }
    return render(request, 'SmartVest/results.html', context)

@login_required
def save_portfolio(request):
    if request.method == 'POST':
        name = request.POST.get('portfolio_name')
        description = request.POST.get('portfolio_description', '')
        
        # Load current results from CSV
        results_path = os.path.join(settings.BASE_DIR, 'alocare_finala_portofoliu.csv')
        portfolio_data = []
        
        if os.path.exists(results_path):
            try:
                df = pd.read_csv(results_path)
                # Cleaning columns
                df.columns = [c.replace(' ', '_').replace('($)', 'USD').replace('(', '').replace(')', '') for c in df.columns]
                portfolio_data = df.to_dict('records')
            except Exception as e:
                print(f"Error reading CSV for saving: {e}")
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
                portfolio_data=portfolio_data
            )
            messages.success(request, f"Portfolio '{name}' saved successfully!")
            return redirect('portfolio-list')
            
    return redirect('view-results')

import yfinance as yf
from .utils import get_portfolio_performance

@login_required
def track_performance(request):
    portfolios = SavedPortfolio.objects.filter(user=request.user)
    performance_data = get_portfolio_performance(portfolios)

    context = {
        'performance_data': performance_data
    }
    return render(request, 'SmartVest/portfolio_performance.html', context)

# ==========================
# MARKET NEWS
# ==========================
from gnews import GNews

@login_required
def market_news(request):
    # Initialize GNews
    google_news = GNews(language='en', country='US', period='1d', max_results=10)
    
    # Get Business/Finance news
    # GNews doesn't have a direct 'finance' topic in the simple wrapper sometimes, 
    # but 'BUSINESS' is standard. Or we can search for "Stock Market".
    try:
        raw_news = google_news.get_news_by_topic('BUSINESS')
        # Clean keys for Django template compatibility (replace space with underscore)
        news_results = []
        for article in raw_news:
            clean_article = {k.replace(' ', '_'): v for k, v in article.items()}
            news_results.append(clean_article)
    except Exception as e:
        print(f"GNews Error: {e}")
        news_results = []
    
    return render(request, 'SmartVest/market_news.html', {'news': news_results})

from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib.auth.models import User

# ... existing imports ...

# ==========================
# ADMIN DASHBOARD
# ==========================
@user_passes_test(lambda u: u.is_superuser)
def admin_dashboard(request):
    # Statistics
    total_users = User.objects.count()
    total_portfolios = SavedPortfolio.objects.count()
    
    # User Details
    users = User.objects.all().order_by('-date_joined')
    user_data = []
    
    for u in users:
        portfolio_count = SavedPortfolio.objects.filter(user=u).count()
        user_data.append({
            'user': u,
            'portfolio_count': portfolio_count
        })

    context = {
        'total_users': total_users,
        'total_portfolios': total_portfolios,
        'user_data': user_data
    }
    return render(request, 'SmartVest/admin_dashboard.html', context)

@user_passes_test(lambda u: u.is_superuser)
def admin_user_detail(request, user_id):
    user = get_object_or_404(User, pk=user_id)
    portfolios = SavedPortfolio.objects.filter(user=user)
    performance_data = get_portfolio_performance(portfolios)
    
    context = {
        'target_user': user,
        'performance_data': performance_data
    }
    return render(request, 'SmartVest/admin_user_detail.html', context)

# ==========================
# CUSTOM FILTERS & PRESETS
# ==========================
from .models import FilterPreset
import json

# All available Finviz filters organized by category
FINVIZ_FILTERS = {
    'descriptive': {
        'Exchange': ['Any', 'AMEX', 'NASDAQ', 'NYSE'],
        'Market Cap.': ['Any', 'Mega ($200bln and more)', 'Large ($10bln to $200bln)', '+Large (over $10bln)', 
                       'Mid ($2bln to $10bln)', '+Mid (over $2bln)', 'Small ($300mln to $2bln)', 
                       '+Small (over $300mln)', 'Micro ($50mln to $300mln)', 'Nano (under $50mln)'],
        'Dividend Yield': ['Any', 'None (0%)', 'Positive (>0%)', 'High (>5%)', 'Very High (>10%)'],
        'Average Volume': ['Any', 'Under 50K', 'Under 100K', 'Under 500K', 'Under 750K', 'Under 1M', 
                          'Over 50K', 'Over 100K', 'Over 200K', 'Over 300K', 'Over 400K', 'Over 500K', 
                          'Over 750K', 'Over 1M', 'Over 2M'],
        'Relative Volume': ['Any', 'Over 0.25', 'Over 0.5', 'Over 1', 'Over 1.5', 'Over 2', 'Over 3', 
                           'Over 5', 'Over 10', 'Under 0.5', 'Under 0.75', 'Under 1', 'Under 1.5', 'Under 2'],
        'Float': ['Any', 'Under 1M', 'Under 5M', 'Under 10M', 'Under 20M', 'Under 50M', 'Under 100M', 
                  'Over 1M', 'Over 2M', 'Over 5M', 'Over 10M', 'Over 20M', 'Over 50M', 'Over 100M', 'Over 200M', 'Over 500M'],
        'Sector': ['Any', 'Basic Materials', 'Communication Services', 'Consumer Cyclical', 
                   'Consumer Defensive', 'Energy', 'Financial', 'Healthcare', 'Industrials', 
                   'Real Estate', 'Technology', 'Utilities'],
        'Industry': ['Any'],  # Too many to list, we'll keep "Any" for simplicity
        'Country': ['Any', 'USA', 'Foreign (ex-USA)', 'China', 'Japan', 'UK', 'Canada', 'Germany', 'France'],
    },
    'fundamental': {
        'P/E': ['Any', 'Low (<15)', 'Profitable (>0)', 'High (>50)', 'Under 5', 'Under 10', 'Under 15', 
                'Under 20', 'Under 25', 'Under 30', 'Under 35', 'Under 40', 'Under 45', 'Under 50', 
                'Over 5', 'Over 10', 'Over 15', 'Over 20', 'Over 25', 'Over 30', 'Over 35', 'Over 40', 'Over 50'],
        'Forward P/E': ['Any', 'Low (<15)', 'Profitable (>0)', 'High (>50)', 'Under 5', 'Under 10', 
                       'Under 15', 'Under 20', 'Under 25', 'Under 30', 'Over 5', 'Over 10', 'Over 15', 
                       'Over 20', 'Over 25', 'Over 30', 'Over 35', 'Over 40', 'Over 50'],
        'PEG': ['Any', 'Low (<1)', 'High (>2)', 'Under 1', 'Under 2', 'Under 3', 'Over 1', 'Over 2', 'Over 3'],
        'P/S': ['Any', 'Low (<1)', 'High (>10)', 'Under 1', 'Under 2', 'Under 3', 'Under 4', 'Under 5', 
                'Under 6', 'Under 7', 'Under 8', 'Under 9', 'Under 10', 'Over 1', 'Over 2', 'Over 3', 
                'Over 4', 'Over 5', 'Over 6', 'Over 7', 'Over 8', 'Over 9', 'Over 10'],
        'P/B': ['Any', 'Low (<1)', 'High (>5)', 'Under 1', 'Under 2', 'Under 3', 'Under 4', 'Under 5', 
                'Under 6', 'Under 7', 'Under 8', 'Under 9', 'Under 10', 'Over 1', 'Over 2', 'Over 3', 
                'Over 4', 'Over 5', 'Over 6', 'Over 7', 'Over 8', 'Over 9', 'Over 10'],
        'EPS growthnext 5 years': ['Any', 'Negative (<0%)', 'Positive (>0%)', 'Under 5%', 'Under 10%', 
                                   'Under 15%', 'Under 20%', 'Under 25%', 'Under 30%', 'Over 5%', 
                                   'Over 10%', 'Over 15%', 'Over 20%', 'Over 25%', 'Over 30%'],
        'EPS growththis year': ['Any', 'Negative (<0%)', 'Positive (>0%)', 'Over 5%', 'Over 10%', 
                               'Over 15%', 'Over 20%', 'Over 25%', 'Over 30%'],
        'EPS growthnext year': ['Any', 'Negative (<0%)', 'Positive (>0%)', 'Over 5%', 'Over 10%', 
                               'Over 15%', 'Over 20%', 'Over 25%', 'Over 30%'],
        'Return on Equity': ['Any', 'Positive (>0%)', 'Negative (<0%)', 'Very Positive (>30%)', 
                            'Over +5%', 'Over +10%', 'Over +15%', 'Over +20%', 'Over +25%', 
                            'Over +30%', 'Under +5%', 'Under +10%', 'Under +15%', 'Under +20%', 
                            'Under +25%', 'Under +30%', 'Under -15%', 'Under -30%'],
        'Return on Assets': ['Any', 'Positive (>0%)', 'Negative (<0%)', 'Very Positive (>15%)', 
                            'Over +5%', 'Over +10%', 'Over +15%', 'Over +20%', 'Over +25%'],
        'Return on Investment': ['Any', 'Positive (>0%)', 'Negative (<0%)', 'Very Positive (>25%)', 
                                'Over +5%', 'Over +10%', 'Over +15%', 'Over +20%', 'Over +25%'],
        'Current Ratio': ['Any', 'High (>3)', 'Low (<1)', 'Under 1', 'Under 0.5', 'Over 0.5', 
                         'Over 1', 'Over 1.5', 'Over 2', 'Over 3', 'Over 4', 'Over 5', 'Over 10'],
        'Debt/Equity': ['Any', 'High (>0.5)', 'Low (<0.1)', 'Under 0.1', 'Under 0.2', 'Under 0.3', 
                       'Under 0.4', 'Under 0.5', 'Under 0.6', 'Under 0.7', 'Under 0.8', 'Under 0.9', 
                       'Under 1', 'Over 0.1', 'Over 0.2', 'Over 0.3', 'Over 0.4', 'Over 0.5', 
                       'Over 0.6', 'Over 0.7', 'Over 0.8', 'Over 0.9', 'Over 1'],
        'Gross Margin': ['Any', 'Positive (>0%)', 'Negative (<0%)', 'High (>50%)', 'Over 0%', 
                        'Over 10%', 'Over 20%', 'Over 30%', 'Over 40%', 'Over 50%', 'Over 60%', 
                        'Over 70%', 'Over 80%', 'Over 90%'],
        'Operating Margin': ['Any', 'Positive (>0%)', 'Negative (<0%)', 'Very Negative (<-20%)', 
                            'High (>25%)', 'Over 0%', 'Over 5%', 'Over 10%', 'Over 15%', 'Over 20%', 
                            'Over 25%', 'Over 30%'],
        'Net Profit Margin': ['Any', 'Positive (>0%)', 'Negative (<0%)', 'Very Negative (<-20%)', 
                             'High (>20%)', 'Over 0%', 'Over 5%', 'Over 10%', 'Over 15%', 'Over 20%', 
                             'Over 25%', 'Over 30%'],
    },
    'technical': {
        '20-Day Simple Moving Average': ['Any', 'Price below SMA20', 'Price 10% below SMA20', 
                                         'Price 20% below SMA20', 'Price 30% below SMA20', 
                                         'Price 40% below SMA20', 'Price 50% below SMA20', 
                                         'Price above SMA20', 'Price 10% above SMA20', 
                                         'Price 20% above SMA20', 'Price 30% above SMA20', 
                                         'Price 40% above SMA20', 'Price 50% above SMA20', 
                                         'Price crossed SMA20', 'Price crossed SMA20 above', 
                                         'Price crossed SMA20 below', 'SMA20 crossed SMA50', 
                                         'SMA20 crossed SMA50 above', 'SMA20 crossed SMA50 below'],
        '50-Day Simple Moving Average': ['Any', 'Price below SMA50', 'Price 10% below SMA50', 
                                         'Price 20% below SMA50', 'Price 30% below SMA50', 
                                         'Price 40% below SMA50', 'Price 50% below SMA50', 
                                         'Price above SMA50', 'Price 10% above SMA50', 
                                         'Price 20% above SMA50', 'Price 30% above SMA50', 
                                         'Price 40% above SMA50', 'Price 50% above SMA50', 
                                         'Price crossed SMA50', 'Price crossed SMA50 above', 
                                         'Price crossed SMA50 below', 'SMA50 crossed SMA200', 
                                         'SMA50 crossed SMA200 above', 'SMA50 crossed SMA200 below'],
        '200-Day Simple Moving Average': ['Any', 'Price below SMA200', 'Price 10% below SMA200', 
                                          'Price 20% below SMA200', 'Price 30% below SMA200', 
                                          'Price 40% below SMA200', 'Price 50% below SMA200', 
                                          'Price above SMA200', 'Price 10% above SMA200', 
                                          'Price 20% above SMA200', 'Price 30% above SMA200', 
                                          'Price 40% above SMA200', 'Price 50% above SMA200', 
                                          'Price crossed SMA200', 'Price crossed SMA200 above', 
                                          'Price crossed SMA200 below'],
        'RSI (14)': ['Any', 'Overbought (90)', 'Overbought (80)', 'Overbought (70)', 'Overbought (60)', 
                    'Oversold (40)', 'Oversold (30)', 'Oversold (20)', 'Oversold (10)', 
                    'Not Overbought (<60)', 'Not Overbought (<50)', 'Not Oversold (>50)', 
                    'Not Oversold (>40)'],
        'Beta': ['Any', 'Under 0', 'Under 0.5', 'Under 1', 'Under 1.5', 'Under 2', 
                 'Over 0', 'Over 0.5', 'Over 1', 'Over 1.5', 'Over 2', 'Over 2.5', 
                 'Over 3', 'Over 4'],
        'Volatility': ['Any', 'Week - Over 3%', 'Week - Over 4%', 'Week - Over 5%', 
                      'Week - Over 6%', 'Week - Over 7%', 'Week - Over 8%', 'Week - Over 9%', 
                      'Week - Over 10%', 'Week - Over 12%', 'Week - Over 15%', 
                      'Month - Over 2%', 'Month - Over 3%', 'Month - Over 4%', 
                      'Month - Over 5%', 'Month - Over 6%', 'Month - Over 8%', 
                      'Month - Over 10%'],
        'Gap': ['Any', 'Up', 'Up 0%', 'Up 1%', 'Up 2%', 'Up 3%', 'Up 4%', 'Up 5%', 
                'Down', 'Down 0%', 'Down 1%', 'Down 2%', 'Down 3%', 'Down 4%', 'Down 5%'],
        '52W High/Low': ['Any', 'New High', 'New Low', '0-3% below High', '0-5% below High', 
                        '0-10% below High', '5-10% below High', '10-15% below High', 
                        '15-20% below High', '20-30% below High', '30-40% below High', 
                        '40-50% below High', '50%+ below High', '0-3% above Low', 
                        '0-5% above Low', '0-10% above Low', '5-10% above Low', 
                        '10-15% above Low', '15-20% above Low', '20-30% above Low', 
                        '30-40% above Low', '40-50% above Low', '50%+ above Low'],
        'Pattern': ['Any', 'Horizontal S/R', 'Horizontal S/R (Strong)', 'TL Resistance', 
                   'TL Resistance (Strong)', 'TL Support', 'TL Support (Strong)', 
                   'Wedge Up', 'Wedge Up (Strong)', 'Wedge Down', 'Wedge Down (Strong)', 
                   'Triangle Ascending', 'Triangle Ascending (Strong)', 'Triangle Descending', 
                   'Triangle Descending (Strong)', 'Wedge', 'Wedge (Strong)', 
                   'Channel Up', 'Channel Up (Strong)', 'Channel Down', 'Channel Down (Strong)', 
                   'Channel', 'Channel (Strong)', 'Double Top', 'Double Bottom', 
                   'Multiple Top', 'Multiple Bottom', 'Head & Shoulders', 'Head & Shoulders Inverse'],
    }
}

@login_required
def custom_filters(request):
    """Page with all Finviz filter options"""
    presets = FilterPreset.objects.filter(user=request.user)
    
    context = {
        'filters': FINVIZ_FILTERS,
        'presets': presets,
        'filters_json': json.dumps(FINVIZ_FILTERS)
    }
    return render(request, 'SmartVest/custom_filters.html', context)

@login_required
def save_preset(request):
    """Save a new filter preset via AJAX"""
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            name = data.get('name', 'My Preset')
            filters = data.get('filters', {})
            
            # Create preset
            preset = FilterPreset.objects.create(
                user=request.user,
                name=name,
                filters=filters
            )
            
            return JsonResponse({
                'success': True, 
                'preset_id': preset.id,
                'message': f'Preset "{name}" salvat cu succes!'
            })
        except Exception as e:
            return JsonResponse({'success': False, 'message': str(e)})
    
    return JsonResponse({'success': False, 'message': 'Invalid request'})

@login_required
def delete_preset(request, pk):
    """Delete a filter preset"""
    preset = get_object_or_404(FilterPreset, pk=pk, user=request.user)
    preset_name = preset.name
    preset.delete()
    messages.success(request, f'Preset "{preset_name}" șters cu succes!')
    return redirect('presets-list')

@login_required
def presets_list(request):
    """List all user's filter presets"""
    presets = FilterPreset.objects.filter(user=request.user)
    return render(request, 'SmartVest/presets_list.html', {'presets': presets})

@login_required
def update_preset(request, pk):
    """Update a filter preset's name and description"""
    preset = get_object_or_404(FilterPreset, pk=pk, user=request.user)
    
    if request.method == 'POST':
        preset.name = request.POST.get('name', preset.name)
        preset.description = request.POST.get('description', preset.description)
        preset.save()
        messages.success(request, f'Preset "{preset.name}" actualizat cu succes!')
        return redirect('presets-list')
    
    return redirect('presets-list')

@login_required  
def run_with_preset(request, pk):
    """Run analysis with a saved preset's filters"""
    global ALGO_RUNNING
    
    preset = get_object_or_404(FilterPreset, pk=pk, user=request.user)
    
    if ALGO_RUNNING:
        messages.warning(request, "O analiză este deja în desfășurare!")
        return redirect('analysis-status')
    
    budget = float(request.GET.get('budget', 10000))
    
    # Start analysis with custom filters
    thread = threading.Thread(target=run_algo_script_custom, args=(preset.filters, budget))
    thread.daemon = True
    thread.start()
    
    messages.success(request, f"Analiză pornită cu preset-ul '{preset.name}' și buget ${budget:,.2f}.")
    return redirect('analysis-status')

def run_algo_script_custom(filters_dict, budget=10000.0):
    """Run algorithm with custom filters"""
    global ALGO_RUNNING
    ALGO_RUNNING = True
    print(f"Starting Algorithm with Custom Filters and Budget: ${budget}...")
    try:
        script_path = os.path.join(settings.BASE_DIR, 'selection_algorithm.py')
        
        # Save filters to temp file to avoid shell escaping issues
        temp_filters_path = os.path.join(settings.BASE_DIR, 'temp_custom_filters.json')
        with open(temp_filters_path, 'w', encoding='utf-8') as f:
            json.dump(filters_dict, f)
        
        command = ["python", script_path, "--custom-filters-file", temp_filters_path, "--budget", str(budget)]
        
        subprocess.run(command, cwd=settings.BASE_DIR, check=True)
        print("Algorithm Script Finished.")
        
        # Cleanup temp file
        if os.path.exists(temp_filters_path):
            os.remove(temp_filters_path)
    except Exception as e:
        print(f"Algorithm Error: {e}")
    finally:
        ALGO_RUNNING = False

from django.http import JsonResponse

def get_user_presets(request):
    """Get presets for sidebar - returns as context"""
    if request.user.is_authenticated:
        return FilterPreset.objects.filter(user=request.user)[:5]
    return []


# ==========================
# UNICORN SCANNER
# ==========================
from .models import WatchedUnicorn
import sys
import os

# Add project root to path for importing unicorn_scanner
sys.path.insert(0, settings.BASE_DIR)

@login_required
def unicorn_scanner(request):
    """Main unicorn scanner page - two-step UX with relax option"""
    from unicorn_scanner import scan_for_unicorns
    
    scan_results = []
    error_message = None
    is_scanning = False
    show_relax_prompt = False   # Show "relax filters?" prompt
    is_relaxed = False          # Are we showing relaxed (2/3) results?
    has_perfect_results = False # Did we find any 3/3 stocks?
    
    if request.method == 'POST':
        if 'run_scan' in request.POST:
            # --- FRESH SCAN ---
            try:
                is_scanning = True
                df_all_scored, _ = scan_for_unicorns()
                
                if not df_all_scored.empty:
                    all_results = df_all_scored.to_dict('records')
                    # Store ALL scored results in session
                    request.session['unicorn_all_results'] = all_results
                    request.session.modified = True
                    
                    # Filter to 3/3 first
                    perfect = [r for r in all_results if r.get('Unicorn_Score', 0) >= 3]
                    
                    if perfect:
                        # Found 3/3 — show them and offer to relax
                        scan_results = perfect
                        has_perfect_results = True
                        show_relax_prompt = True
                    else:
                        # No 3/3 — prompt to relax
                        strong = [r for r in all_results if r.get('Unicorn_Score', 0) >= 2]
                        if strong:
                            show_relax_prompt = True
                            error_message = f"Nu am gasit companii cu scor perfect (3/3), dar exista {len(strong)} companii cu scor 2/3."
                        else:
                            error_message = "Nu s-au gasit candidati unicorn. Incearca din nou mai tarziu."
                else:
                    error_message = "Scanarea nu a returnat rezultate. Incearca din nou mai tarziu."
            except Exception as e:
                error_message = f"Eroare la scanare: {str(e)}"
                print(f"Unicorn scan error: {e}")
        
        elif 'relax_filters' in request.POST:
            # --- RELAX: show 2/3 from cached data ---
            all_results = request.session.get('unicorn_all_results', [])
            if all_results:
                # Include both 3/3 and 2/3
                scan_results = [r for r in all_results if r.get('Unicorn_Score', 0) >= 2]
                is_relaxed = True
                has_perfect_results = any(r.get('Unicorn_Score', 0) >= 3 for r in scan_results)
            else:
                error_message = "Nu exista rezultate anterioare. Ruleaza o scanare noua."
    else:
        # GET request — check for cached relaxed/perfect results
        all_results = request.session.get('unicorn_all_results', [])
        if all_results:
            # Default: show 3/3 if available, otherwise show whatever we showed last
            perfect = [r for r in all_results if r.get('Unicorn_Score', 0) >= 3]
            if perfect:
                scan_results = perfect
                has_perfect_results = True
                show_relax_prompt = True
            else:
                strong = [r for r in all_results if r.get('Unicorn_Score', 0) >= 2]
                if strong:
                    show_relax_prompt = True
    
    # Also store filtered results for watchlist add functionality
    if scan_results:
        request.session['unicorn_results'] = scan_results
        request.session.modified = True
    
    # Get user's watchlist
    watchlist = WatchedUnicorn.objects.filter(user=request.user)
    watched_tickers = [w.ticker for w in watchlist]
    
    # Fetch real-time prices for watchlist items
    watchlist_with_pl = []
    if watchlist:
        tickers_to_fetch = [w.ticker for w in watchlist if w.entry_price]
        if tickers_to_fetch:
            try:
                # Fetch current data from yfinance
                price_data = yf.download(tickers_to_fetch, period='2d', progress=False)
                
                for w in watchlist:
                    item = {
                        'pk': w.pk,
                        'ticker': w.ticker,
                        'company_name': w.company_name,
                        'entry_price': float(w.entry_price) if w.entry_price else None,
                        'added_at': w.added_at,
                        'notes': w.notes,
                        'current_price': None,
                        'daily_pl': None,
                        'daily_pl_pct': None,
                        'open_pl': None,
                        'open_pl_pct': None,
                    }
                    
                    try:
                        if len(tickers_to_fetch) > 1:
                            close_data = price_data['Close'][w.ticker].dropna()
                        else:
                            close_data = price_data['Close'].dropna()
                        
                        if len(close_data) >= 1:
                            current_price = float(close_data.iloc[-1])
                            item['current_price'] = round(current_price, 2)
                            
                            # Calculate Daily P/L (if we have 2 days of data)
                            if len(close_data) >= 2:
                                prev_close = float(close_data.iloc[-2])
                                daily_pl = current_price - prev_close
                                daily_pl_pct = (daily_pl / prev_close) * 100
                                item['daily_pl'] = round(daily_pl, 2)
                                item['daily_pl_pct'] = round(daily_pl_pct, 2)
                            
                            # Calculate Open P/L (since entry)
                            if item['entry_price']:
                                open_pl = current_price - item['entry_price']
                                open_pl_pct = (open_pl / item['entry_price']) * 100
                                item['open_pl'] = round(open_pl, 2)
                                item['open_pl_pct'] = round(open_pl_pct, 2)
                    except Exception as e:
                        print(f"Error processing {w.ticker}: {e}")
                    
                    watchlist_with_pl.append(item)
            except Exception as e:
                print(f"Error fetching prices: {e}")
                # Fallback to basic watchlist data
                for w in watchlist:
                    watchlist_with_pl.append({
                        'pk': w.pk,
                        'ticker': w.ticker,
                        'company_name': w.company_name,
                        'entry_price': float(w.entry_price) if w.entry_price else None,
                        'added_at': w.added_at,
                        'notes': w.notes,
                        'current_price': None,
                        'daily_pl': None,
                        'daily_pl_pct': None,
                        'open_pl': None,
                        'open_pl_pct': None,
                    })
        else:
            # No entry prices, just show basic data
            for w in watchlist:
                watchlist_with_pl.append({
                    'pk': w.pk,
                    'ticker': w.ticker,
                    'company_name': w.company_name,
                    'entry_price': None,
                    'added_at': w.added_at,
                    'notes': w.notes,
                    'current_price': None,
                    'daily_pl': None,
                    'daily_pl_pct': None,
                    'open_pl': None,
                    'open_pl_pct': None,
                })
    
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


@login_required
def add_to_watchlist(request, ticker):
    """Add a stock to user's unicorn watchlist"""
    if request.method == 'POST':
        # Get cached results from session
        scan_results = request.session.get('unicorn_results', [])
        
        # Find the stock info
        stock_info = next((s for s in scan_results if s.get('Ticker') == ticker), None)
        
        # Check if already watched
        if WatchedUnicorn.objects.filter(user=request.user, ticker=ticker).exists():
            messages.warning(request, f'{ticker} este deja în watchlist!')
        else:
            WatchedUnicorn.objects.create(
                user=request.user,
                ticker=ticker,
                company_name=stock_info.get('Company', '') if stock_info else '',
                entry_price=stock_info.get('Price') if stock_info else None,
            )
            messages.success(request, f'{ticker} a fost adăugat în watchlist! 🦄')
    
    return redirect('unicorn-scanner')


@login_required
def remove_from_watchlist(request, pk):
    """Remove a stock from user's unicorn watchlist"""
    watched = get_object_or_404(WatchedUnicorn, pk=pk, user=request.user)
    ticker = watched.ticker
    watched.delete()
    messages.success(request, f'{ticker} a fost șters din watchlist.')
    return redirect('unicorn-scanner')


# ==========================
# BACKTESTING (ADMIN-ONLY)
# ==========================

# Global progress tracker for backtest
BACKTEST_PROGRESS = {
    'percent': 0,
    'message': 'Idle',
    'running': False,
    'result': None,
}

def _backtest_progress_callback(message, percent):
    """Called by BacktestEngine to report progress."""
    global BACKTEST_PROGRESS
    BACKTEST_PROGRESS['percent'] = percent
    BACKTEST_PROGRESS['message'] = message


def _run_backtest_thread(start_date, end_date, profile_type, initial_capital):
    """Run backtest in background thread."""
    global BACKTEST_PROGRESS
    BACKTEST_PROGRESS['running'] = True
    BACKTEST_PROGRESS['result'] = None
    BACKTEST_PROGRESS['percent'] = 0
    BACKTEST_PROGRESS['message'] = 'Se inițializează...'
    
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
        BACKTEST_PROGRESS['result'] = result.to_dict()
        BACKTEST_PROGRESS['percent'] = 100
        BACKTEST_PROGRESS['message'] = 'Backtest finalizat!'
        
    except Exception as e:
        print(f"Backtest error: {e}")
        BACKTEST_PROGRESS['result'] = {
            'metrics': {'error': str(e)},
            'profile_type': profile_type,
            'start_date': start_date,
            'end_date': end_date,
            'initial_capital': initial_capital,
            'equity_curve': {'dates': [], 'values': []},
            'benchmark_curve': {'dates': [], 'values': []},
            'snapshots': [],
        }
        BACKTEST_PROGRESS['percent'] = 100
        BACKTEST_PROGRESS['message'] = f'Eroare: {str(e)}'
    finally:
        BACKTEST_PROGRESS['running'] = False


@login_required
@user_passes_test(lambda u: u.is_superuser)
def backtest_view(request):
    """Main backtesting page — admin only."""
    global BACKTEST_PROGRESS
    
    result = None
    
    if request.method == 'POST':
        if BACKTEST_PROGRESS.get('running'):
            messages.warning(request, "Un backtest este deja în desfășurare!")
            return redirect('backtest')
        
        # Parse form data
        period_years = int(request.POST.get('period', 2))
        profile_type = request.POST.get('profile_type', 'balanced')
        try:
            initial_capital = float(request.POST.get('initial_capital', 10000))
        except ValueError:
            initial_capital = 10000.0
        
        # Calculate dates
        end_date = datetime.date.today().strftime('%Y-%m-%d')
        start_date = (datetime.date.today() - datetime.timedelta(days=period_years * 365)).strftime('%Y-%m-%d')
        
        # Start backtest in background
        thread = threading.Thread(
            target=_run_backtest_thread,
            args=(start_date, end_date, profile_type, initial_capital)
        )
        thread.daemon = True
        thread.start()
        
        messages.success(request, f"Backtest pornit: {profile_type.title()}, {period_years}Y, ${initial_capital:,.0f}")
        
        # Wait for completion (with timeout)
        import time as time_module
        max_wait = 600  # 10 minutes max
        waited = 0
        while BACKTEST_PROGRESS.get('running') and waited < max_wait:
            time_module.sleep(1)
            waited += 1
        
        # Get result
        if BACKTEST_PROGRESS.get('result'):
            result = BACKTEST_PROGRESS['result']
            
            # Format allocations as percentages for display
            if result.get('snapshots'):
                for snap in result['snapshots']:
                    if snap.get('allocations'):
                        snap['allocations'] = {
                            k: round(v * 100, 1) 
                            for k, v in snap['allocations'].items() 
                            if v > 0
                        }
    
    elif BACKTEST_PROGRESS.get('result'):
        # GET request — show last result if available
        result = BACKTEST_PROGRESS['result']
        if result.get('snapshots'):
            for snap in result['snapshots']:
                if snap.get('allocations'):
                    # Only format if values are in 0-1 range (not already formatted)
                    first_val = next(iter(snap['allocations'].values()), 0)
                    if first_val <= 1:
                        snap['allocations'] = {
                            k: round(v * 100, 1) 
                            for k, v in snap['allocations'].items() 
                            if v > 0
                        }
    
    context = {
        'result': result,
        'running': BACKTEST_PROGRESS.get('running', False),
    }
    return render(request, 'SmartVest/backtest.html', context)


@login_required
@user_passes_test(lambda u: u.is_superuser)
def backtest_progress_api(request):
    """AJAX endpoint for polling backtest progress."""
    return JsonResponse({
        'percent': BACKTEST_PROGRESS.get('percent', 0),
        'message': BACKTEST_PROGRESS.get('message', 'Idle'),
        'running': BACKTEST_PROGRESS.get('running', False),
    })


@login_required
@user_passes_test(lambda u: u.is_superuser)
def backtest_results(request):
    """Admin-only page showing all automated backtest results."""
    from django.db.models import Avg, Count, Min, Max

    # Filter by profile if requested
    profile_filter = request.GET.get('profile', '')
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

    # Win rate (return > 0)
    total_done = runs.count()
    wins = runs.filter(total_return__gt=0).count()
    win_rate = (wins / total_done * 100) if total_done > 0 else 0

    # Beat SPY rate (outperformance > 0)
    beat_spy = runs.filter(outperformance__gt=0).count()
    beat_spy_rate = (beat_spy / total_done * 100) if total_done > 0 else 0

    # Per-profile breakdown
    profile_stats = {}
    for p in ['conservative', 'balanced', 'aggressive']:
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

    # Sorting
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
    """Detail view for a single backtest run — shows full charts and data."""
    import json
    run = get_object_or_404(BacktestRun, pk=pk)

    equity_curve = run.equity_curve_json or {}
    benchmark_curve = run.benchmark_curve_json or {}
    snapshots = run.snapshots_json or []

    # Build a result dict matching the format used by backtest.html
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
        # Pre-serialized JSON for safe JavaScript embedding
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
