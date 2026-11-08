from django.db import IntegrityError, transaction
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from common.errors import ApiError
from materials.models import Material
from personas.models import Persona

from .greetings import greeting_for
from .models import Lesson, LessonTerm, Message
from .serializers import (
    LessonStartRequest,
    MessagePageQuery,
    lesson_detail_data,
    lesson_messages_data,
    lesson_start_data,
)

MAX_MESSAGE_LIMIT = 200


def get_own_material(user, material_id):
    """내 자료. 없으면 404, 다른 사용자의 자료면 403."""
    material = Material.objects.filter(pk=material_id).first()
    if material is None:
        raise ApiError(404, 'NOT_FOUND', '자료를 찾을 수 없어요.')
    if material.user_id != user.id:
        raise ApiError(403, 'FORBIDDEN', '접근할 수 없는 데이터예요.')
    return material


def get_own_lesson(user, lesson_id):
    """내 수업. 없으면 404, 다른 사용자의 수업이면 403."""
    lesson = Lesson.objects.select_related('material', 'persona').filter(pk=lesson_id).first()
    if lesson is None:
        raise ApiError(404, 'NOT_FOUND', '수업을 찾을 수 없어요.')
    if lesson.user_id != user.id:
        raise ApiError(403, 'FORBIDDEN', '접근할 수 없는 데이터예요.')
    return lesson


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


class LessonDetailView(APIView):
    """GET /api/lessons/{lesson_id}: 수업 정보 + 용어 체크리스트"""

    def get(self, request, lesson_id):
        lesson = get_own_lesson(request.user, lesson_id)
        return Response(lesson_detail_data(lesson))


class LessonMessagesView(APIView):
    """GET /api/lessons/{lesson_id}/messages: 수업 대화 + 손 든 표시

    ?before=<message_id>&limit=50: id < before인 메시지 중 최근 limit개를 시간순으로.
    hand_raises는 돌려주는 메시지 바로 아래에 그릴 것(after_message가 그 메시지들 중 하나)만 준다.
    """

    def get(self, request, lesson_id):
        lesson = get_own_lesson(request.user, lesson_id)
        query = MessagePageQuery(data=request.query_params)
        if not query.is_valid():
            raise ApiError(400, 'VALIDATION_ERROR', 'before와 limit은 숫자여야 해요.')
        before = query.validated_data.get('before')
        limit = min(query.validated_data['limit'], MAX_MESSAGE_LIMIT)

        messages = lesson.messages.all()
        if before is not None:
            messages = messages.filter(id__lt=before)
        messages = list(messages.order_by('-id')[:limit])[::-1]  # 최근 limit개를 시간순으로
        hand_raises = lesson.hand_raises.filter(after_message_id__in=[m.id for m in messages])
        return Response(lesson_messages_data(messages, hand_raises))
