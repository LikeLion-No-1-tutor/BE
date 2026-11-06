from django.urls import path
from .views import GoogleLoginView

urlpatterns = [
    path('api/auth/google', GoogleLoginView.as_view(), name='google-login'),
]