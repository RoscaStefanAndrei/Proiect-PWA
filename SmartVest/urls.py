from django.urls import path, include
from django.contrib.auth import views as auth_views
from . import views

urlpatterns = [
    path('', views.home, name='home'),
    path('register/', views.register, name='register'),
    path('profile/', views.profile, name='profile'),
    path('login/', auth_views.LoginView.as_view(template_name='SmartVest/login.html'), name='login'),
    path('logout/', auth_views.LogoutView.as_view(template_name='SmartVest/logout.html'), name='logout'),
    
    # Saved Portfolios
    path('portfolios/', views.PortfolioListView.as_view(), name='portfolio-list'),
    path('analysis/save/', views.save_portfolio, name='save-portfolio'),
    path('portfolios/<int:pk>/delete/', views.PortfolioDeleteView.as_view(), name='portfolio-delete'),
    path('portfolios/<int:pk>/', views.PortfolioDetailView.as_view(), name='portfolio-detail'), # We defined this as pass, need to fix view logic later
    path('analysis/performance/', views.track_performance, name='track-performance'),
    path('news/', views.market_news, name='market-news'),
    path('custom-admin/', views.admin_dashboard, name='admin-dashboard'),
    path('custom-admin/user/<int:user_id>/', views.admin_user_detail, name='admin-user-detail'),

    # Algorithm
    path('analysis/', views.run_analysis, name='run-analysis'),
    path('analysis/select/', views.select_portfolio_type, name='select-portfolio-type'),
    path('analysis/status/', views.analysis_status, name='analysis-status'),
    path('analysis/results/', views.view_results, name='view-results'),
]
