from django.db import IntegrityError, transaction
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from common.errors import ApiError
from materials.models import Material
from personas.models import Persona

from .greetings import greeting_for
from .models import Lesson, LessonTerm, Message
from .serializers import LessonStartRequest, lesson_start_data


def get_own_material(user, material_id):
    """내 자료. 없으면 404, 다른 사용자의 자료면 403."""
    material = Material.objects.filter(pk=material_id).first()
    if material is None:
        raise ApiError(404, 'NOT_FOUND', '자료를 찾을 수 없어요.')
    if material.user_id != user.id:
        raise ApiError(403, 'FORBIDDEN', '접근할 수 없는 데이터예요.')
    return material


class LessonListView(APIView):
    """POST /api/lessons — 수업 시작 (권한은 기본값: 로그인 + 닉네임)"""

    def post(self, request):
        body = LessonStartRequest(data=request.data)
        if not body.is_valid():
            raise ApiError(400, 'VALIDATION_ERROR', 'material_id와 persona_id가 필요해요.')

        material = get_own_material(request.user, body.validated_data['material_id'])
        persona = Persona.objects.filter(pk=body.validated_data['persona_id']).first()
        if persona is None:
            raise ApiError(404, 'NOT_FOUND', '페르소나를 찾을 수 없어요.')
        if material.status != Material.Status.READY:
            raise ApiError(409, 'MATERIAL_NOT_READY', '자료 정리가 아직 끝나지 않았어요.')
        if Lesson.objects.filter(material=material).exists():
            raise ApiError(409, 'MATERIAL_ALREADY_USED', '이미 수업에 쓴 자료예요.')

        try:
            with transaction.atomic():
                lesson = Lesson.objects.create(user=request.user, material=material, persona=persona)
                LessonTerm.objects.bulk_create(
                    LessonTerm(lesson=lesson, term=term) for term in material.terms.all()
                )
                greeting = Message.objects.create(
                    lesson=lesson,
                    sender=Message.Sender.STUDENT,
                    kind=Message.Kind.GREETING,
                    content=greeting_for(persona, material.title),
                )
        except IntegrityError:
            # 같은 자료로 거의 동시에 두 번 시작한 경우. lessons.material_id UNIQUE가 막아 줌
            raise ApiError(409, 'MATERIAL_ALREADY_USED', '이미 수업에 쓴 자료예요.')

        return Response(lesson_start_data(lesson, greeting), status=status.HTTP_201_CREATED)
