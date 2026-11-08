from django.urls import path

from .views import LessonDetailView, LessonListView, LessonMessagesView

urlpatterns = [
    path('api/lessons', LessonListView.as_view(), name='lesson-list'),
    path('api/lessons/<int:lesson_id>', LessonDetailView.as_view(), name='lesson-detail'),
    path('api/lessons/<int:lesson_id>/messages', LessonMessagesView.as_view(), name='lesson-messages'),
]
