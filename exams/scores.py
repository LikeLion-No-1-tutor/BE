"""점수 기록 계산. 저장하지 않고 exams로 계산한다 (ERD 설계 메모 '이전 점수 비교').

prefetch_related('exams')로 미리 가져온 수업에 쓰면 쿼리를 더 하지 않는다.
"""
from .models import Exam


def score_history(lesson):
    """이 수업의 completed 시험을 completed_at 순으로 (평가 → 재시험 1 → 재시험 2 …)."""
    completed = [exam for exam in lesson.exams.all() if exam.status == Exam.Status.COMPLETED]
    return sorted(completed, key=lambda exam: (exam.completed_at, exam.id))


def evaluation_score(lesson):
    """학생 AI 평가 점수. 평가가 끝나지 않았으면 None."""
    for exam in lesson.exams.all():
        if exam.kind == Exam.Kind.EVALUATION and exam.status == Exam.Status.COMPLETED:
            return exam.score
    return None


def latest_score(lesson):
    """재시험까지 포함한 가장 최근 점수. 끝난 시험이 없으면 None."""
    history = score_history(lesson)
    return history[-1].score if history else None


def retest_count(lesson):
    return sum(1 for exam in score_history(lesson) if exam.kind == Exam.Kind.RETEST)


def comparison(history):
    """가장 최근 점수와 바로 앞 점수. 시험이 2개 미만이면 None."""
    if len(history) < 2:
        return None
    current, previous = history[-1].score, history[-2].score
    return {'current_score': current, 'previous_score': previous, 'diff': current - previous}
