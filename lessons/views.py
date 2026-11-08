from django.db import IntegrityError, transaction
from django.utils import timezone
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from common import ai_client
from common.errors import ApiError
from materials.models import Material
from personas.models import Persona

from . import ai
from .greetings import greeting_for
from .models import HandRaise, Lesson, LessonTerm, Message
from .serializers import (
    LessonStartRequest,
    MessagePageQuery,
    MessageSendRequest,
    lesson_detail_data,
    lesson_messages_data,
    lesson_start_data,
    message_sent_data,
    question_asked_data,
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


def ensure_teaching(lesson):
    if lesson.status != Lesson.Status.TEACHING:
        raise ApiError(409, 'LESSON_NOT_TEACHING', '이미 종료된 수업이에요.')


def lock_teaching_lesson(lesson_id):
    """트랜잭션 안에서 수업을 잠그고 아직 가르치는 중인지 다시 확인한다 (AI를 기다리는 사이 종료됐을 수 있음)."""
    lesson = Lesson.objects.select_for_update().get(pk=lesson_id)
    ensure_teaching(lesson)
    return lesson


def call_ai(request, path, payload, parse):
    """실시간 AI 호출. 실패하거나 응답 모양이 틀리면 502 AI_ERROR (아무것도 저장하지 않은 상태)."""
    try:
        return ai_client.call(
            path, json=payload, request_id=request.request_id, user_id=request.user.id,
            mode=ai_client.REALTIME, parse=parse,
        )
    except ai_client.AiError as error:
        raise error.to_api_error()


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
    """/api/lessons/{lesson_id}/messages
    GET: 수업 대화 + 손 든 표시, POST: 설명·답변 보내기

    GET

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

    def post(self, request, lesson_id):
        lesson = get_own_lesson(request.user, lesson_id)
        ensure_teaching(lesson)
        body = MessageSendRequest(data=request.data)
        if not body.is_valid():
            raise ApiError(400, 'VALIDATION_ERROR', '설명은 1~3,000자여야 해요.')
        content = body.validated_data['content']
        reply_to = self._question_to_answer(lesson, body.validated_data.get('reply_to_id'))
        kind = Message.Kind.ANSWER if reply_to else Message.Kind.EXPLANATION

        # AI를 기다리는 동안에는 트랜잭션을 열지 않는다. 실패하면 아무것도 저장하지 않음
        payload = ai.analyze_payload(lesson, kind, content, reply_to)
        term_updates, hand_raise_reason = call_ai(request, ai.ANALYZE_PATH, payload, ai.parse_analyze_result)

        with transaction.atomic():
            lesson = lock_teaching_lesson(lesson.id)
            message = Message.objects.create(
                lesson=lesson, sender=Message.Sender.TEACHER, kind=kind, content=content, reply_to=reply_to,
            )
            changed_terms = self._apply_term_updates(lesson, message, term_updates)
            new_hand_raise = None
            if hand_raise_reason:
                new_hand_raise = HandRaise.objects.create(
                    lesson=lesson, after_message=message, reason=hand_raise_reason,
                )

        data = message_sent_data(lesson, message, changed_terms, new_hand_raise)
        return Response(data, status=status.HTTP_201_CREATED)

    @staticmethod
    def _question_to_answer(lesson, reply_to_id):
        """reply_to_id가 있으면 이 수업의 학생 질문이어야 한다."""
        if reply_to_id is None:
            return None
        question = lesson.messages.filter(pk=reply_to_id, kind=Message.Kind.QUESTION).first()
        if question is None:
            raise ApiError(400, 'VALIDATION_ERROR', 'reply_to_id가 이 수업의 학생 질문이 아니에요.')
        return question

    @staticmethod
    def _apply_term_updates(lesson, message, term_updates):
        """올라가는 판정만 반영한다 (todo → mentioned → explained). 이 수업에 없는 term_id는 무시."""
        lesson_terms = {
            lesson_term.term_id: lesson_term
            for lesson_term in lesson.lesson_terms.select_related('term').select_for_update()
        }
        changed = []
        for term_id, new_status in term_updates:
            lesson_term = lesson_terms.get(term_id)
            if lesson_term is None or ai.TERM_RANK[new_status] <= ai.TERM_RANK[lesson_term.status]:
                continue
            lesson_term.status = new_status
            lesson_term.message = message
            lesson_term.save(update_fields=['status', 'message', 'updated_at'])
            if lesson_term not in changed:
                changed.append(lesson_term)
        return sorted(changed, key=lambda t: (t.term.display_order, t.term_id))


class HandRaiseAskView(APIView):
    """POST /api/lessons/{lesson_id}/hand-raises/{hand_raise_id}/ask: 질문 받기"""

    def post(self, request, lesson_id, hand_raise_id):
        lesson = get_own_lesson(request.user, lesson_id)
        hand_raise = lesson.hand_raises.filter(pk=hand_raise_id).first()
        if hand_raise is None:
            raise ApiError(404, 'NOT_FOUND', '손 든 표시를 찾을 수 없어요.')
        ensure_teaching(lesson)
        if hand_raise.status != HandRaise.Status.RAISED:
            raise ApiError(409, 'HAND_ALREADY_ASKED', '이미 질문한 손 든 표시예요.')

        content = call_ai(request, ai.QUESTION_PATH, ai.question_payload(lesson, hand_raise), ai.parse_question_result)

        with transaction.atomic():
            lesson = lock_teaching_lesson(lesson.id)
            hand_raise = HandRaise.objects.select_for_update().get(pk=hand_raise.pk)
            if hand_raise.status != HandRaise.Status.RAISED:  # 버튼을 두 번 누른 경우
                raise ApiError(409, 'HAND_ALREADY_ASKED', '이미 질문한 손 든 표시예요.')
            question = Message.objects.create(
                lesson=lesson, sender=Message.Sender.STUDENT, kind=Message.Kind.QUESTION, content=content,
            )
            hand_raise.status = HandRaise.Status.ASKED
            hand_raise.question_message = question
            hand_raise.asked_at = timezone.now()
            hand_raise.save(update_fields=['status', 'question_message', 'asked_at'])

        return Response(question_asked_data(lesson, hand_raise, question), status=status.HTTP_201_CREATED)
