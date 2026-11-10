"""페르소나 API의 문서 (Swagger). API 동작에는 쓰지 않습니다."""
from rest_framework import serializers

from common.docs import MEMBER, errors, operation

from .serializers import PersonaSerializer


class PersonaListResponse(serializers.Serializer):
    items = PersonaSerializer(many=True)


persona_list = operation(
    'persona_list', '페르소나', '페르소나 목록',
    description='가르칠 학생 AI 3명입니다. 화면에 보여 줄 순서대로 줍니다.',
    responses={200: PersonaListResponse, **errors(MEMBER)},
)
