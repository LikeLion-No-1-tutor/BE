from django.urls import path

from .views import MaterialCreateView, MaterialDetailView

urlpatterns = [
    path('api/materials', MaterialCreateView.as_view(), name='material-create'),
    path('api/materials/<int:material_id>', MaterialDetailView.as_view(), name='material-detail'),
]
