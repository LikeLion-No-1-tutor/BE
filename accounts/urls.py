from django.urls import path

from .views import GoogleLoginView, LogoutView, MeView, TokenRefreshView

urlpatterns = [
    path('api/auth/google', GoogleLoginView.as_view(), name='google-login'),
    path('api/auth/refresh', TokenRefreshView.as_view(), name='token-refresh'),
    path('api/auth/logout', LogoutView.as_view(), name='logout'),
    path('api/users/me', MeView.as_view(), name='users-me'),
]
