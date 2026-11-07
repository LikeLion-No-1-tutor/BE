from django.urls import path

from .views import MaterialCreateView

urlpatterns = [
    path('api/materials', MaterialCreateView.as_view(), name='material-create'),
]
