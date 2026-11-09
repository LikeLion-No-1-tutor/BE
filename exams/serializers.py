"""성장보고서 API의 응답 모양. 놓친 개념·점수 비교는 저장하지 않고 여기서 계산한다."""
from rest_framework import serializers

from lessons.models import LessonTerm
from lessons.serializers import iso

from .models import Exam
from .scores import comparison, latest_score, retest_count, score_history


class RetestStartRequest(serializers.Serializer):
    """재시험 출제 요청. focus를 빼면 missed_terms."""

    focus = serializers.ChoiceField(choices=['missed_terms', 'all'], default='missed_terms')


class AnswerRequest(serializers.Serializer):
    """문제 풀이 요청. 앞뒤 공백을 지운 뒤 비어 있으면 안 됨."""

    response = serializers.CharField(max_length=3000)


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


def retest_data(exam, report_id):
    """재시험 문제·상태. 정답·해설은 답을 낸 문제에만 넣는다."""
    questions = []
    for question in exam.questions.all():
        item = {
            'number': question.number,
            'question_type': question.question_type,
            'content': question.content,
            'choices': question.choices,
            'answered': question.response is not None,
        }
        if item['answered']:
            item.update({
                'response': question.response,
                'is_correct': question.is_correct,
                'correct_answer': question.correct_answer,
                'explanation': question.explanation,
            })
        questions.append(item)
    return {
        'id': exam.id,
        'report_id': report_id,
        'status': exam.status,
        'total': exam.question_count,
        'error': exam.error,
        'questions': questions,
    }


def answer_result_data(question):
    """문제 풀이 및 채점의 응답."""
    return {
        'number': question.number,
        'is_correct': question.is_correct,
        'correct_answer': question.correct_answer,
        'explanation': question.explanation,
    }
