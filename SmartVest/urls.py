from django.urls import path, include
from django.contrib.auth import views as auth_views
from . import views

urlpatterns = [
    path('', views.home, name='home'),
    path('register/', views.register, name='register'),
    path('profile/', views.profile, name='profile'),
    path('login/', auth_views.LoginView.as_view(template_name='SmartVest/login.html'), name='login'),
    path('logout/', auth_views.LogoutView.as_view(template_name='SmartVest/logout.html'), name='logout'),
    path('profile/delete/', views.delete_profile, name='delete-profile'),
    
    # Saved Portfolios
    path('portfolios/', views.PortfolioListView.as_view(), name='portfolio-list'),
    path('analysis/save/', views.save_portfolio, name='save-portfolio'),
    path('portfolios/<int:pk>/delete/', views.PortfolioDeleteView.as_view(), name='portfolio-delete'),
    path('portfolios/<int:pk>/', views.PortfolioDetailView.as_view(), name='portfolio-detail'),
    path('analysis/performance/', views.track_performance, name='track-performance'),
    path('news/', views.market_news, name='market-news'),
    path('custom-admin/', views.admin_dashboard, name='admin-dashboard'),
    path('custom-admin/user/<int:user_id>/', views.admin_user_detail, name='admin-user-detail'),

    # Algorithm
    path('analysis/', views.run_analysis, name='run-analysis'),
    path('analysis/select/', views.select_portfolio_type, name='select-portfolio-type'),
    path('analysis/status/', views.analysis_status, name='analysis-status'),
    path('analysis/results/', views.view_results, name='view-results'),
    
    # Custom Filters & Presets
    path('analysis/custom-filters/', views.custom_filters, name='custom-filters'),
    path('presets/', views.presets_list, name='presets-list'),
    path('presets/save/', views.save_preset, name='save-preset'),
    path('presets/<int:pk>/delete/', views.delete_preset, name='delete-preset'),
    path('presets/<int:pk>/update/', views.update_preset, name='update-preset'),
    path('presets/<int:pk>/run/', views.run_with_preset, name='run-with-preset'),
    
    # Unicorn Scanner
    path('unicorns/', views.unicorn_scanner, name='unicorn-scanner'),
    path('unicorns/watch/<str:ticker>/', views.add_to_watchlist, name='add-to-watchlist'),
    path('unicorns/unwatch/<int:pk>/', views.remove_from_watchlist, name='remove-from-watchlist'),
]

