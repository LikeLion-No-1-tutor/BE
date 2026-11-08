from django.urls import path

from .views import LessonListView

urlpatterns = [
    path('api/lessons', LessonListView.as_view(), name='lesson-list'),
]
