"""성장보고서 API의 응답 모양. 놓친 개념·점수 비교는 저장하지 않고 여기서 계산한다."""
from lessons.models import LessonTerm
from lessons.serializers import iso

from .models import Exam
from .scores import comparison, latest_score, retest_count, score_history


def report_list_item(report):
    """성장보고서 목록의 한 줄. lesson__material은 select_related, lesson__exams는 prefetch."""
    lesson = report.lesson
    return {
        'id': report.id,
        'lesson_id': lesson.id,
        'title': lesson.material.title,
        'score': report.score,
        'latest_score': latest_score(lesson),
        'retest_count': retest_count(lesson),
        'created_at': iso(report.created_at),
    }


def report_detail_data(report):
    """성장보고서 상세."""
    lesson = report.lesson
    history = score_history(lesson)
    evaluation = next((exam for exam in lesson.exams.all() if exam.kind == Exam.Kind.EVALUATION), None)
    questions = list(evaluation.questions.all()) if evaluation is not None else []
    lesson_terms = list(lesson.lesson_terms.select_related('term'))

    wrong_by_term = {}
    for question in questions:
        if question.is_correct is False and question.term_id is not None:
            wrong_by_term[question.term_id] = wrong_by_term.get(question.term_id, 0) + 1

    return {
        'id': report.id,
        'lesson': {
            'id': lesson.id,
            'title': lesson.material.title,
            'persona_name': lesson.persona.name,
            'persona_grade_label': lesson.persona.grade_label,
            'started_at': iso(lesson.started_at),
        },
        'score': report.score,
        'score_history': [
            {'exam_id': exam.id, 'kind': exam.kind, 'score': exam.score, 'completed_at': iso(exam.completed_at)}
            for exam in history
        ],
        'comparison': comparison(history),
        'exam': {
            'correct': evaluation.correct_count if evaluation is not None else None,
            'total': evaluation.question_count if evaluation is not None else None,
            'results': [
                {'number': q.number, 'is_correct': q.is_correct, 'term_id': q.term_id} for q in questions
            ],
        },
        'terms': {
            'explained': sum(1 for lt in lesson_terms if lt.status == LessonTerm.Status.EXPLAINED),
            'total': len(lesson_terms),
        },
        'strengths': report.strengths,
        'missed_terms': [
            {
                'term_id': lt.term_id,
                'name': lt.term.name,
                'status': lt.status,
                'wrong_count': wrong_by_term.get(lt.term_id, 0),
            }
            for lt in lesson_terms
            if lt.status != LessonTerm.Status.EXPLAINED
        ],
        'review_recommendations': report.review_recommendations,
        'created_at': iso(report.created_at),
        'updated_at': iso(report.updated_at),
    }
