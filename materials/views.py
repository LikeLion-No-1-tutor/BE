from django.conf import settings
from django.db import transaction
from rest_framework import status
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView

from common import jobs
from common.errors import ApiError
from common.middleware import get_request_id

from . import docs, storage
from .models import Material
from .tasks import material_process

# PDF, PPT(X), DOC(X), TXT, MD, 이미지(PNG·JPG), 소스코드
ALLOWED_EXTS = {
    'pdf', 'ppt', 'pptx', 'doc', 'docx', 'txt', 'md', 'png', 'jpg', 'jpeg',
    'py', 'js', 'ts', 'jsx', 'tsx', 'java', 'kt', 'c', 'h', 'cpp', 'hpp', 'cs', 'go', 'rs',
    'swift', 'rb', 'php', 'html', 'css', 'sql', 'sh',
}


IMAGE_EXTS = {'png', 'jpg', 'jpeg'}


def _validation_error(message):
    return ApiError(status.HTTP_400_BAD_REQUEST, 'VALIDATION_ERROR', message)


class MaterialCreateView(APIView):
    """08. 학습 자료 업로드 — POST /api/materials (multipart/form-data)

    자료를 임시 저장소에 두고 바로 202를 돌려줍니다. 용어 체크리스트·요약정리는 백그라운드에서 만듭니다.
    """

    parser_classes = [MultiPartParser, FormParser, JSONParser]

    @docs.material_upload
    def post(self, request):
        title = request.data.get('title')
        uploaded = request.FILES.get('file')
        text = request.data.get('text')
        if isinstance(text, str) and not text.strip():
            text = None

        # 1. 확인: 제목, 파일·텍스트 중 하나만, 확장자, 크기
        if not isinstance(title, str) or not 1 <= len(title.strip()) <= 100 or (uploaded is None) == (text is None):
            raise _validation_error('제목과 함께 파일이나 텍스트 중 하나만 보내 주세요.')
        if text is not None and not isinstance(text, str):
            raise _validation_error('제목과 함께 파일이나 텍스트 중 하나만 보내 주세요.')
        title = title.strip()

        max_bytes = settings.MAX_UPLOAD_MB * 1024 * 1024
        ext = None
        if uploaded is not None:
            name = uploaded.name or ''
            ext = name.rsplit('.', 1)[-1].lower() if '.' in name else ''
            if ext not in ALLOWED_EXTS:
                raise ApiError(status.HTTP_400_BAD_REQUEST, 'UNSUPPORTED_FILE_TYPE', '지원하지 않는 파일 형식이에요.')
            limit = settings.MAX_IMAGE_MB * 1024 * 1024 if ext in IMAGE_EXTS else max_bytes
            if uploaded.size > limit:
                raise ApiError(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, 'FILE_TOO_LARGE', '파일이 너무 커요.')
        elif len(text.encode('utf-8')) > max_bytes:
            raise ApiError(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, 'FILE_TOO_LARGE', '텍스트가 너무 길어요.')

        # 2. materials 생성, 원본은 임시 저장소에
        with transaction.atomic():
            material = Material.objects.create(
                user=request.user,
                title=title,
                source_type=Material.SourceType.FILE if uploaded else Material.SourceType.TEXT,
                file_name=(uploaded.name[:255] if uploaded else None),
                file_ext=ext,
                status=Material.Status.PROCESSING,
            )
            try:
                if uploaded is not None:
                    storage.save_file(material.id, uploaded, ext)
                else:
                    storage.save_text(material.id, text)
            except OSError:
                storage.delete(material.id)
                raise  # 트랜잭션 롤백 → 500

            # 3. 커밋한 뒤 백그라운드 작업 등록
            jobs.enqueue(material_process, material.id, get_request_id(request))

        return Response(
            {'id': material.id, 'title': material.title, 'status': material.status},
            status=status.HTTP_202_ACCEPTED,
        )


def _step(done, running):
    if done:
        return 'done'
    return 'running' if running else 'pending'


class MaterialDetailView(APIView):
    """09. 자료 정리 상태 — GET /api/materials/{material_id}

    자료 제출 화면이 1~2초마다 불러 진행 목록을 그립니다.
    steps는 저장하지 않고 컬럼으로 계산합니다. 용어 정의와 요약정리는 내려주지 않습니다.
    """

    @docs.material_status
    def get(self, request, material_id):
        material = Material.objects.filter(pk=material_id).first()
        if material is None:
            raise ApiError(status.HTTP_404_NOT_FOUND, 'NOT_FOUND', '자료를 찾을 수 없어요.')
        if material.user_id != request.user.id:
            raise ApiError(status.HTTP_403_FORBIDDEN, 'FORBIDDEN', '접근할 수 없는 데이터예요.')

        processing = material.status == Material.Status.PROCESSING
        term_count = material.terms.count()
        terms_done = term_count > 0
        summary_done = bool(material.summary)
        deleted = material.original_deleted_at is not None

        return Response(
            {
                'id': material.id,
                'title': material.title,
                'source_type': material.source_type,
                'file_name': material.file_name,
                'status': material.status,
                'steps': {
                    # 정리를 시작하면 바로 done (변환은 짧아 따로 보여 주지 않음)
                    'read': 'done',
                    'terms': _step(terms_done, processing),
                    'summary': _step(summary_done, terms_done and processing),
                    'original_deleted': _step(deleted, summary_done and not deleted),
                },
                'term_count': term_count,
                'error': material.error,
            },
            status=status.HTTP_200_OK,
        )
