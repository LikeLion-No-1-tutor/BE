"""수업 API의 요청 검사와 응답 모양.

응답은 명세의 JSON 모양을 그대로 보이게 하려고 dict를 직접 만든다.
학생 AI 내부용인 hand_raises.reason, 용어 정의, 요약정리는 어떤 응답에도 넣지 않는다.
"""
from rest_framework import serializers

_datetime = serializers.DateTimeField()


def iso(value):
    """ISO 8601, 한국 시간 (settings.TIME_ZONE). None이면 None."""
    return None if value is None else _datetime.to_representation(value)


class LessonStartRequest(serializers.Serializer):
    material_id = serializers.IntegerField()
    persona_id = serializers.IntegerField()


class MessagePageQuery(serializers.Serializer):
    """수업 대화 조회의 ?before=<message_id>&limit=50"""

    before = serializers.IntegerField(required=False, min_value=1)
    limit = serializers.IntegerField(required=False, min_value=1, default=50)  # 200을 넘으면 200으로


def material_brief(material):
    return {'id': material.id, 'title': material.title}


def persona_brief(persona):
    return {'id': persona.id, 'name': persona.name, 'grade_label': persona.grade_label}


def lesson_term_data(lesson_term):
    return {'term_id': lesson_term.term_id, 'name': lesson_term.term.name, 'status': lesson_term.status}


def message_data(message, with_reply_to=True):
    data = {
        'id': message.id,
        'sender': message.sender,
        'kind': message.kind,
        'content': message.content,
    }
    if with_reply_to:
        data['reply_to_id'] = message.reply_to_id
    data['created_at'] = iso(message.created_at)
    return data


def lesson_start_data(lesson, greeting):
    """수업 시작의 응답."""
    lesson_terms = lesson.lesson_terms.select_related('term')
    return {
        'id': lesson.id,
        'status': lesson.status,
        'material': material_brief(lesson.material),
        'persona': persona_brief(lesson.persona),
        'terms': [lesson_term_data(lesson_term) for lesson_term in lesson_terms],
        'messages': [message_data(greeting, with_reply_to=False)],
    }


def hand_raise_data(hand_raise):
    """reason(학생 AI 내부 메모)은 넣지 않는다."""
    return {
        'id': hand_raise.id,
        'after_message_id': hand_raise.after_message_id,
        'status': hand_raise.status,
        'question_message_id': hand_raise.question_message_id,
    }


def _related_id(lesson, name):
    """1:1 역참조(note, report)의 id. 없으면 None."""
    related = getattr(lesson, name, None)
    return related.id if related is not None else None


def lesson_detail_data(lesson):
    """수업 정보 + 용어 체크리스트의 응답."""
    from .models import HandRaise, LessonTerm

    lesson_terms = list(lesson.lesson_terms.select_related('term'))
    return {
        'id': lesson.id,
        'status': lesson.status,
        'material': material_brief(lesson.material),
        'persona': persona_brief(lesson.persona),
        'terms': [lesson_term_data(lesson_term) for lesson_term in lesson_terms],
        'term_summary': {
            'explained': sum(1 for t in lesson_terms if t.status == LessonTerm.Status.EXPLAINED),
            'total': len(lesson_terms),
        },
        'raised_hand_count': lesson.hand_raises.filter(status=HandRaise.Status.RAISED).count(),
        'note_id': _related_id(lesson, 'note'),
        'report_id': _related_id(lesson, 'report'),
        'started_at': iso(lesson.started_at),
        'ended_at': iso(lesson.ended_at),
    }


def lesson_messages_data(messages, hand_raises):
    """수업 대화 + 손 든 표시의 응답."""
    return {
        'messages': [message_data(message) for message in messages],
        'hand_raises': [hand_raise_data(hand_raise) for hand_raise in hand_raises],
    }
