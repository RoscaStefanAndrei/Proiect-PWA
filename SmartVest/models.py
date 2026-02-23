from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone

class UserProfile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    avatar = models.ImageField(upload_to='avatars/', default='avatars/default.png', blank=True)
    bio = models.TextField(max_length=500, blank=True)

    def __str__(self):
        return f'{self.user.username} Profile'

class SavedPortfolio(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    name = models.CharField(max_length=100)
    description = models.TextField(blank=True)
    portfolio_data = models.JSONField(default=dict)
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.name

class AnalysisHistory(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    date_run = models.DateTimeField(default=timezone.now)
    summary = models.TextField(blank=True) # JSON or text summary of the run
    
    def __str__(self):
        return f"Analysis run by {self.user.username} on {self.date_run}"

class FilterPreset(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    name = models.CharField(max_length=100)
    description = models.TextField(blank=True, default='')  # User notes about this preset
    filters = models.JSONField(default=dict)  # Stores Finviz filter key-value pairs
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['-created_at']
    
    def __str__(self):
        return f"{self.name} - {self.user.username}"


class WatchedUnicorn(models.Model):
    """Tracks stocks in user's unicorn watchlist"""
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    ticker = models.CharField(max_length=10)
    company_name = models.CharField(max_length=200, blank=True)
    added_at = models.DateTimeField(auto_now_add=True)
    entry_price = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    target_price = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    notes = models.TextField(blank=True)
    
    class Meta:
        ordering = ['-added_at']
        unique_together = ['user', 'ticker']  # Prevent duplicate watchlist entries
    
    def __str__(self):
        return f"{self.ticker} - {self.user.username}"


class BacktestRun(models.Model):
    """Stores the result of a single automated backtest run."""
    STATUS_CHOICES = [
        ('running', 'Running'),
        ('done', 'Done'),
        ('failed', 'Failed'),
    ]

    # Auto-generated name: bkt_agresiv_1, bkt_balansat_2, etc.
    name = models.CharField(max_length=100, unique=True)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='running')

    # Parameters
    profile_type = models.CharField(max_length=20)
    start_date = models.DateField()
    end_date = models.DateField()
    initial_capital = models.FloatField(default=10000.0)
    rebalance_months = models.IntegerField(default=3)

    # Key metrics (nullable — filled on completion)
    total_return = models.FloatField(null=True, blank=True)
    cagr = models.FloatField(null=True, blank=True)
    sharpe_ratio = models.FloatField(null=True, blank=True)
    sortino_ratio = models.FloatField(null=True, blank=True)
    max_drawdown = models.FloatField(null=True, blank=True)
    max_drawdown_duration = models.IntegerField(null=True, blank=True)
    calmar_ratio = models.FloatField(null=True, blank=True)
    annual_volatility = models.FloatField(null=True, blank=True)
    alpha = models.FloatField(null=True, blank=True)
    beta = models.FloatField(null=True, blank=True)
    benchmark_return = models.FloatField(null=True, blank=True)
    outperformance = models.FloatField(null=True, blank=True)
    final_value = models.FloatField(null=True, blank=True)
    n_trading_days = models.IntegerField(null=True, blank=True)

    # Rebalance info
    n_rebalances = models.IntegerField(default=0)
    n_stocks_avg = models.FloatField(null=True, blank=True)

    # Detail data (for drill-down view)
    equity_curve_json = models.JSONField(default=dict, blank=True)
    benchmark_curve_json = models.JSONField(default=dict, blank=True)
    snapshots_json = models.JSONField(default=list, blank=True)

    # Metadata
    created_at = models.DateTimeField(auto_now_add=True)
    duration_seconds = models.FloatField(null=True, blank=True)
    error_message = models.TextField(blank=True, default='')

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return self.name
