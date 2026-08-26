from django.urls import path
from . import views

app_name = 'downloader'

urlpatterns = [
    path('', views.index_view, name='index'),
    path('login/', views.login_view, name='login'),
    path('signup/', views.signup_view, name='signup'),
    path('admin-dashboard/', views.admin_dashboard_view, name='admin_dashboard'),
    path('download/<str:record_id>/', views.download_file_view, name='download_file'),
    path('api/inspect/', views.api_inspect, name='api_inspect'),
    path('api/history/', views.api_history, name='api_history'),
    path('api/history/delete/', views.api_delete_history, name='api_delete_history'),
    path('api/history/clear/', views.api_clear_history, name='api_clear_history'),
    path('api/convert-images/', views.api_convert_images, name='api_convert_images'),
    path('api/auth/login/', views.api_auth_login, name='api_auth_login'),
    path('api/auth/register/', views.api_auth_register, name='api_auth_register'),
    path('api/auth/register/send-code/', views.api_auth_send_code, name='api_auth_send_code'),
    path('api/auth/register/verify/', views.api_auth_verify_code, name='api_auth_verify_code'),
    path('api/auth/google/', views.api_google_auth, name='api_google_auth'),
    path('api/auth/me/', views.api_auth_me, name='api_auth_me'),
    path('api/auth/logout/', views.api_auth_logout, name='api_auth_logout'),
    path('api/admin/users/', views.api_admin_users, name='api_admin_users'),
    path('api/admin/toggle-premium/', views.api_admin_toggle_premium, name='api_admin_toggle_premium'),
    path('api/admin/history/', views.api_admin_history, name='api_admin_history'),
]

