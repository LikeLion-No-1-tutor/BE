"""수업 중 AI 서버 호출에 보낼 데이터 만들기와 받은 응답 확인 (용어 판정·손 들기, 질문 만들기).

학생 AI에게 가는 부분(용어 판정·손 들기의 student, 질문 만들기 전체)에는 용어 정의·요약정리·정답을 절대 넣지 않는다.
용어 정의는 용어 판정(judge) 부분에만 들어간다.

parse_* 함수는 ai_client.call의 parse로 넘긴다. 응답 모양이 틀리면 ValueError를 던지고, ai_client가 INVALID_RESPONSE 실패로 처리한다.
"""
from .models import HandRaise, LessonTerm

ANALYZE_PATH = '/lessons/messages/analyze'  # 용어 판정 + 손 들기
QUESTION_PATH = '/lessons/questions'  # 손 든 표시의 질문 만들기

# 용어 상태는 올라가기만 한다: todo → mentioned → explained
TERM_RANK = {LessonTerm.Status.TODO: 0, LessonTerm.Status.MENTIONED: 1, LessonTerm.Status.EXPLAINED: 2}


def persona_payload(persona):
    return {
        'code': persona.code,
        'name': persona.name,
        'grade_label': persona.grade_label,
        'system_prompt': persona.system_prompt,
    }


def message_payload(message):
    return {
        'id': message.id,
        'sender': message.sender,
        'kind': message.kind,
        'content': message.content,
        'reply_to_id': message.reply_to_id,
    }


def analyze_payload(lesson, kind, content, reply_to):
    """용어 판정·손 들기 요청. 방금 보낸 메시지는 아직 저장 전이라 id가 None."""
    pending_terms = (
        lesson.lesson_terms.select_related('term')
        .exclude(status=LessonTerm.Status.EXPLAINED)
    )
    raised_reasons = lesson.hand_raises.filter(status=HandRaise.Status.RAISED).values_list('reason', flat=True)
    new_message = {
        'id': None,
        'sender': 'teacher',
        'kind': kind,
        'content': content,
        'reply_to_id': reply_to.id if reply_to else None,
    }
    return {
        'judge': {
            'message': {'kind': kind, 'content': content},
            'reply_to_question': reply_to.content if reply_to else None,
            'terms': [
                {
                    'term_id': lesson_term.term_id,
                    'name': lesson_term.term.name,
                    'definition': lesson_term.term.definition,
                    'status': lesson_term.status,
                }
                for lesson_term in pending_terms
            ],
        },
        'student': {
            'persona': persona_payload(lesson.persona),
            'messages': [message_payload(m) for m in lesson.messages.all()] + [new_message],
            'raised_reasons': list(raised_reasons),
        },
    }


def question_payload(lesson, hand_raise):
    """질문 만들기 요청. 버튼을 누른 시점까지의 대화 전체와 손 든 이유."""
    return {
        'persona': persona_payload(lesson.persona),
        'messages': [message_payload(m) for m in lesson.messages.all()],
        'reason': hand_raise.reason,
    }


def parse_analyze_result(body):
    """용어 판정·손 들기 응답에서 (용어 판정 목록, 손 든 이유 또는 None)을 꺼낸다."""
    term_updates = body.get('term_updates')
    hand_raise = body.get('hand_raise')
    if not isinstance(term_updates, list):
        raise ValueError('term_updates가 배열이 아님')
    updates = []
    for item in term_updates:
        if not isinstance(item, dict) or not isinstance(item.get('term_id'), int):
            raise ValueError('term_updates 항목 형식이 틀림')
        if item.get('status') in TERM_RANK:
            updates.append((item['term_id'], item['status']))
    if hand_raise is None:
        return updates, None
    if not isinstance(hand_raise, dict) or not isinstance(hand_raise.get('reason'), str):
        raise ValueError('hand_raise 형식이 틀림')
    reason = hand_raise['reason'].strip()
    return updates, reason or None


def parse_question_result(body):
    """질문 만들기 응답의 질문 문장."""
    content = body.get('content')
    if not isinstance(content, str) or not content.strip():
        raise ValueError('content가 비었음')
    return content.strip()
