from django.urls import path

from .views import (
    ReportDetailView,
    ReportListView,
    RetestAnswerView,
    RetestCompleteView,
    RetestDetailView,
    RetestStartView,
)

urlpatterns = [
    path('api/reports', ReportListView.as_view(), name='report-list'),
    path('api/reports/<int:report_id>', ReportDetailView.as_view(), name='report-detail'),
    path('api/reports/<int:report_id>/retests', RetestStartView.as_view(), name='retest-start'),
    path('api/retests/<int:retest_id>', RetestDetailView.as_view(), name='retest-detail'),
    path(
        'api/retests/<int:retest_id>/questions/<int:number>/answer',
        RetestAnswerView.as_view(),
        name='retest-answer',
    ),
    path('api/retests/<int:retest_id>/complete', RetestCompleteView.as_view(), name='retest-complete'),
]
