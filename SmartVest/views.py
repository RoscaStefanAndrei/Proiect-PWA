from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib.auth.models import User
from .forms import UserRegisterForm, UserProfileForm
from .models import UserProfile, SavedPortfolio

def home(request):
    return render(request, 'SmartVest/home.html')

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
        p_form = UserProfileForm(request.POST, request.FILES, instance=request.user.userprofile)
        if p_form.is_valid():
            p_form.save()
            messages.success(request, f'Your profile has been updated!')
            return redirect('profile')
    else:
        # Ensure profile exists (fallback for superusers created via CLI)
        if not hasattr(request.user, 'userprofile'):
            UserProfile.objects.create(user=request.user)
            
        p_form = UserProfileForm(instance=request.user.userprofile)

    context = {
        'p_form': p_form
    }
    return render(request, 'SmartVest/profile.html', context)

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

class PortfolioDetailView(LoginRequiredMixin, UserPassesTestMixin, DetailView):
    model = SavedPortfolio
    template_name = 'SmartVest/portfolio_detail.html'

    def test_func(self):
        portfolio = self.get_object()
        if self.request.user == portfolio.user:
            return True
        return False

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
