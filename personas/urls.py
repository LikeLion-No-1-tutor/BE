from django.urls import path

from .views import PersonaListView

urlpatterns = [
    path('api/personas', PersonaListView.as_view(), name='persona-list'),
]
