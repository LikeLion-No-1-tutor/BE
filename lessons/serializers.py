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
