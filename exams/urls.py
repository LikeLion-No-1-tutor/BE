from django.urls import path

from .views import ReportDetailView, ReportListView

urlpatterns = [
    path('api/reports', ReportListView.as_view(), name='report-list'),
    path('api/reports/<int:report_id>', ReportDetailView.as_view(), name='report-detail'),
]
