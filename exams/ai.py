"""평가·재시험·성장보고서의 AI 서버 호출 데이터.

- 학생 AI(문제 풀이)에게는 정답·해설·관련 용어·요약정리를 절대 보내지 않는다.
- parse_* 함수는 응답 모양이 틀리면 ValueError를 던진다. ai_client.call(parse=...)에 넘기면
  INVALID_RESPONSE 실패가 되고, 백그라운드에서는 한 번 다시 부른다.
"""
from lessons.ai import message_payload, persona_payload

from .models import ExamQuestion

GENERATE_PATH = '/exams/generate'  # 평가·재시험 출제
SOLVE_PATH = '/exams/solve'  # 학생 AI 문제 풀이
GRADE_PATH = '/exams/grade'  # 주관식 채점
REPORT_PATH = '/reports/generate'  # 성장보고서 작성

QUESTION_TYPES = {choice for choice, _ in ExamQuestion.QuestionType.choices}


# 출제 -----------------------------------------------------------------

def generate_payload(material, kind, count, question_types, focus_term_ids=(), exclude_questions=()):
    return {
        'kind': kind,
        'summary': material.summary,
        'terms': [{'term_id': term.id, 'name': term.name} for term in material.terms.all()],
        'count': count,
        'question_types': list(question_types),
        'focus_term_ids': list(focus_term_ids),
        'exclude_questions': list(exclude_questions),
    }


def parse_generated(body, term_ids):
    """출제 응답 → ExamQuestion에 넣을 dict 목록. 요청에 없던 term_id는 None으로."""
    questions = body['questions']
    if not isinstance(questions, list) or not questions:
        raise ValueError('questions가 비었음')
    parsed, numbers = [], set()
    for item in questions:
        number = item['number']
        question_type = item['question_type']
        if not isinstance(number, int) or number < 1 or number in numbers:
            raise ValueError(f'number가 잘못됨: {number!r}')
        if question_type not in QUESTION_TYPES:
            raise ValueError(f'question_type이 잘못됨: {question_type!r}')
        content, correct_answer = _text(item['content']), _text(item['correct_answer'])
        explanation = item.get('explanation') or ''
        choices = item.get('choices')
        if question_type == ExamQuestion.QuestionType.MULTIPLE_CHOICE:
            if not isinstance(choices, list) or len(choices) < 2 or not all(isinstance(c, str) for c in choices):
                raise ValueError(f'{number}번 객관식 보기가 잘못됨')
            if correct_answer not in {str(i) for i in range(len(choices))}:
                raise ValueError(f'{number}번 객관식 정답이 보기 번호가 아님: {correct_answer!r}')
        else:
            choices = None
        term_id = item.get('term_id')
        numbers.add(number)
        parsed.append({
            'number': number,
            'question_type': question_type,
            'content': content,
            'choices': choices,
            'correct_answer': correct_answer,
            'explanation': explanation if isinstance(explanation, str) else '',
            'term_id': term_id if term_id in term_ids else None,
        })
    return sorted(parsed, key=lambda q: q['number'])


# 학생 AI 풀이 -----------------------------------------------------------

def solve_payload(lesson, questions):
    """정답·해설·관련 용어는 넣지 않는다."""
    return {
        'persona': persona_payload(lesson.persona),
        'messages': [message_payload(m) for m in lesson.messages.all()],
        'questions': [
            {'number': q.number, 'question_type': q.question_type, 'content': q.content, 'choices': q.choices}
            for q in questions
        ],
    }


def parse_answers(body, numbers):
    """풀이 응답 → {number: response}. 모든 문제에 답이 있어야 한다."""
    answers = {}
    for item in body['answers']:
        if item['number'] in numbers:
            answers[item['number']] = _text(item['response'], allow_blank=True)
    missing = set(numbers) - set(answers)
    if missing:
        raise ValueError(f'답이 없는 문제: {sorted(missing)}')
    return answers


def is_choice_correct(question, response):
    """객관식은 보기 번호 문자열을 그대로 비교한다 (AI를 부르지 않음)."""
    return response.strip() == question.correct_answer.strip()


# 주관식 채점 ------------------------------------------------------------

def grade_payload(questions):
    return {
        'items': [
            {
                'number': q.number,
                'content': q.content,
                'correct_answer': q.correct_answer,
                'explanation': q.explanation,
                'response': q.response,
            }
            for q in questions
        ],
    }


def parse_grades(body, numbers):
    """채점 응답 → {number: is_correct}. reason은 저장하지 않는다."""
    grades = {}
    for item in body['results']:
        if item['number'] in numbers:
            if not isinstance(item['is_correct'], bool):
                raise ValueError(f"{item['number']}번 is_correct가 true/false가 아님")
            grades[item['number']] = item['is_correct']
    missing = set(numbers) - set(grades)
    if missing:
        raise ValueError(f'채점 결과가 없는 문제: {sorted(missing)}')
    return grades


# 성장보고서 -------------------------------------------------------------

def report_payload(lesson, exam):
    """보고서 AI는 학생 역할이 아니므로 페르소나의 system_prompt는 넣지 않는다."""
    lesson_terms = lesson.lesson_terms.select_related('term')
    return {
        'title': lesson.material.title,
        'persona': {'name': lesson.persona.name, 'grade_label': lesson.persona.grade_label},
        'messages': [message_payload(m) for m in lesson.messages.all()],
        'terms': [
            {
                'term_id': lt.term_id,
                'name': lt.term.name,
                'definition': lt.term.definition,
                'status': lt.status,
            }
            for lt in lesson_terms
        ],
        'exam': {
            'correct': exam.correct_count,
            'total': exam.question_count,
            'questions': [
                {
                    'number': q.number,
                    'content': q.content,
                    'correct_answer': q.correct_answer,
                    'response': q.response,
                    'is_correct': q.is_correct,
                    'term_id': q.term_id,
                }
                for q in exam.questions.all()
            ],
        },
    }


def parse_report(body, term_ids):
    """보고서 응답 → (strengths, review_recommendations). 요청에 없던 term_id의 추천은 버린다."""
    strengths = body['strengths']
    recommendations = body['review_recommendations']
    if not isinstance(strengths, list) or not all(isinstance(s, str) for s in strengths):
        raise ValueError('strengths가 문자열 배열이 아님')
    if not isinstance(recommendations, list):
        raise ValueError('review_recommendations가 배열이 아님')
    kept = [
        {'term_id': item['term_id'], 'text': _text(item['text'])}
        for item in recommendations
        if item.get('term_id') in term_ids
    ]
    return strengths, kept


def _text(value, allow_blank=False):
    if not isinstance(value, str) or (not allow_blank and not value.strip()):
        raise ValueError(f'문자열이 아니거나 비었음: {value!r}')
    return value.strip()
