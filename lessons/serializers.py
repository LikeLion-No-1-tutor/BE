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


class MessageSendRequest(serializers.Serializer):
    """설명·답변 보내기 요청. content는 앞뒤 공백을 지운 뒤 1~3000자."""

    content = serializers.CharField(max_length=3000)
    reply_to_id = serializers.IntegerField(required=False, allow_null=True)


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
    lesson_terms = lesson.lesson_terms.select_related('term')
    return {
        'id': lesson.id,
        'status': lesson.status,
        'material': material_brief(lesson.material),
        'persona': persona_brief(lesson.persona),
        'terms': [lesson_term_data(lesson_term) for lesson_term in lesson_terms],
        'term_summary': term_summary(lesson),
        'raised_hand_count': raised_hand_count(lesson),
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


def term_summary(lesson):
    from .models import LessonTerm

    statuses = list(lesson.lesson_terms.values_list('status', flat=True))
    return {
        'explained': sum(1 for value in statuses if value == LessonTerm.Status.EXPLAINED),
        'total': len(statuses),
    }


def raised_hand_count(lesson):
    from .models import HandRaise

    return lesson.hand_raises.filter(status=HandRaise.Status.RAISED).count()


def message_sent_data(lesson, message, changed_terms, new_hand_raise):
    """설명·답변 보내기의 응답. changed_terms는 이번 메시지로 상태가 바뀐 LessonTerm 목록."""
    return {
        'message': message_data(message),
        'term_updates': [lesson_term_data(lesson_term) for lesson_term in changed_terms],
        'term_summary': term_summary(lesson),
        'new_hand_raise': None if new_hand_raise is None else {
            'id': new_hand_raise.id,
            'after_message_id': new_hand_raise.after_message_id,
            'status': new_hand_raise.status,
        },
        'raised_hand_count': raised_hand_count(lesson),
    }


def question_asked_data(lesson, hand_raise, question):
    """질문 받기의 응답."""
    return {
        'hand_raise': hand_raise_data(hand_raise),
        'question': message_data(question, with_reply_to=False),
        'raised_hand_count': raised_hand_count(lesson),
    }


def note_data(note, lesson):
    """정리노트의 응답."""
    return {
        'id': note.id,
        'lesson_id': lesson.id,
        'persona_name': lesson.persona.name,
        'content': note.content,
        'created_at': iso(note.created_at),
    }


def progress_data(lesson, exam_question_count):
    """진행 상태의 응답. 저장하지 않고 note·exams·reports로 계산한다."""
    from exams.models import Exam

    from .models import Lesson

    evaluating = lesson.status == Lesson.Status.EVALUATING
    failed = lesson.status == Lesson.Status.FAILED
    note = getattr(lesson, 'note', None)
    report = getattr(lesson, 'report', None)
    exam = lesson.exams.filter(kind=Exam.Kind.EVALUATION).first()

    if note is not None:
        note_status = 'done'
    elif evaluating:
        note_status = 'running'
    elif failed:
        note_status = 'failed'
    else:
        note_status = 'pending'

    if note_status != 'done' or exam is None:
        exam_status = 'pending'
    else:
        exam_status = exam.status
    solved = exam.questions.exclude(response=None).count() if exam is not None else 0
    total = exam.question_count if exam is not None else exam_question_count

    if report is not None:
        report_status = 'done'
    elif exam_status == Exam.Status.COMPLETED and evaluating:
        report_status = 'running'
    elif exam_status == Exam.Status.COMPLETED and failed:
        report_status = 'failed'
    else:
        report_status = 'pending'

    return {
        'lesson_status': lesson.status,
        'note': {'status': note_status, 'note_id': note.id if note else None},
        'exam': {'status': exam_status, 'solved': solved, 'total': total},
        'report': {'status': report_status, 'report_id': report.id if report else None},
        'error': lesson.error,
    }
