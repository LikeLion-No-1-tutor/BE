"""자료 API의 문서 (Swagger). API 동작에는 쓰지 않습니다."""
from django.conf import settings
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from common.docs import MEMBER, OWNED, StoredError, errors, operation

from .models import Material

STEP_CHOICES = ['done', 'running', 'pending']


@extend_schema_field(OpenApiTypes.BINARY)
class UploadFile(serializers.FileField):
    """Swagger에서 파일 선택 버튼으로 보이게 합니다."""


class MaterialUploadRequest(serializers.Serializer):
    title = serializers.CharField(max_length=100, help_text='1~100자')
    file = UploadFile(required=False, help_text='파일과 텍스트 중 하나만')
    text = serializers.CharField(required=False, help_text='직접 입력한 텍스트. 파일과 텍스트 중 하나만')


class MaterialUploadResponse(serializers.Serializer):
    id = serializers.IntegerField()
    title = serializers.CharField()
    status = serializers.ChoiceField(choices=Material.Status.choices)


class MaterialSteps(serializers.Serializer):
    read = serializers.ChoiceField(choices=STEP_CHOICES, help_text='자료 읽기')
    terms = serializers.ChoiceField(choices=STEP_CHOICES, help_text='용어 체크리스트 만들기')
    summary = serializers.ChoiceField(choices=STEP_CHOICES, help_text='요약정리 만들기')
    original_deleted = serializers.ChoiceField(choices=STEP_CHOICES, help_text='원본 삭제')


class MaterialStatusResponse(serializers.Serializer):
    id = serializers.IntegerField()
    title = serializers.CharField()
    source_type = serializers.ChoiceField(choices=Material.SourceType.choices)
    file_name = serializers.CharField(allow_null=True, help_text='텍스트로 올렸으면 null')
    status = serializers.ChoiceField(choices=Material.Status.choices, help_text='ready가 되면 수업을 시작할 수 있음')
    steps = MaterialSteps()
    term_count = serializers.IntegerField()
    error = StoredError(allow_null=True, help_text='status가 failed일 때만 값이 있음')


material_upload = operation(
    'material_upload', '자료', '학습 자료 업로드',
    description=(
        f'자료를 받고 바로 `202`를 돌려줍니다. 정리는 백그라운드에서 하므로 자료 정리 상태 API로 확인합니다.\n\n'
        f'- 파일: PDF, PPT(X), DOC(X), TXT, MD, PNG, JPG, 소스 코드. 최대 {settings.MAX_UPLOAD_MB}MB, '
        f'이미지는 {settings.MAX_IMAGE_MB}MB\n'
        f'- 텍스트만 보낼 때는 JSON 본문 `{{"title", "text"}}`도 됩니다.'
    ),
    request={'multipart/form-data': MaterialUploadRequest},
    responses={
        202: MaterialUploadResponse,
        **errors(MEMBER, s400=['VALIDATION_ERROR', 'UNSUPPORTED_FILE_TYPE'], s413=['FILE_TOO_LARGE']),
    },
)

material_status = operation(
    'material_status', '자료', '자료 정리 상태',
    description='자료 제출 화면에서 1~2초마다 불러 진행 상황을 그립니다.',
    responses={200: MaterialStatusResponse, **errors(OWNED)},
)
