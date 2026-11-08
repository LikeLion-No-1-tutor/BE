from rest_framework.response import Response
from rest_framework.views import APIView

from common.errors import ApiError
from common.pagination import PagePagination

from .models import Report
from .serializers import report_detail_data, report_list_item


def get_own_report(user, report_id):
    """내 성장보고서. 없으면 404, 다른 사용자의 보고서면 403."""
    report = (
        Report.objects.select_related('lesson__material', 'lesson__persona')
        .prefetch_related('lesson__exams')
        .filter(pk=report_id)
        .first()
    )
    if report is None:
        raise ApiError(404, 'NOT_FOUND', '성장보고서를 찾을 수 없어요.')
    if report.lesson.user_id != user.id:
        raise ApiError(403, 'FORBIDDEN', '접근할 수 없는 데이터예요.')
    return report


class ReportListView(APIView):
    """GET /api/reports: 성장보고서 목록 (최신순)"""

    def get(self, request):
        reports = (
            Report.objects.filter(lesson__user=request.user)
            .select_related('lesson__material')
            .prefetch_related('lesson__exams')
            .order_by('-created_at', '-id')
        )
        paginator = PagePagination()
        page = paginator.paginate_queryset(reports, request, view=self)
        return paginator.get_paginated_response([report_list_item(report) for report in page])


class ReportDetailView(APIView):
    """GET /api/reports/{report_id}: 성장보고서 상세"""

    def get(self, request, report_id):
        return Response(report_detail_data(get_own_report(request.user, report_id)))
