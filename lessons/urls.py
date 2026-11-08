from django.urls import path

from .views import HandRaiseAskView, LessonDetailView, LessonListView, LessonMessagesView

urlpatterns = [
    path('api/lessons', LessonListView.as_view(), name='lesson-list'),
    path('api/lessons/<int:lesson_id>', LessonDetailView.as_view(), name='lesson-detail'),
    path('api/lessons/<int:lesson_id>/messages', LessonMessagesView.as_view(), name='lesson-messages'),
    path(
        'api/lessons/<int:lesson_id>/hand-raises/<int:hand_raise_id>/ask',
        HandRaiseAskView.as_view(),
        name='hand-raise-ask',
    ),
]
