"""평가·재시험·성장보고서. ERD의 exams, exam_questions, reports 테이블."""
from django.db import models

from lessons.models import Lesson
from materials.models import Term


class Exam(models.Model):
    """평가(학생 AI가 풂, 수업당 1개)와 재시험(사용자가 풂, 여러 개)."""

    class Kind(models.TextChoices):
        EVALUATION = 'evaluation'
        RETEST = 'retest'

    class Status(models.TextChoices):
        GENERATING = 'generating'  # 출제 중
        SOLVING = 'solving'  # 푸는 중
        GRADING = 'grading'  # 주관식 채점 중 (평가에서만)
        COMPLETED = 'completed'
        FAILED = 'failed'

    lesson = models.ForeignKey(Lesson, on_delete=models.CASCADE, related_name='exams')
    kind = models.CharField(max_length=20, choices=Kind.choices)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.GENERATING)
    error = models.JSONField(null=True, blank=True)  # 출제·풀이·채점 실패 이유 {code, message, request_id}
    question_count = models.IntegerField()
    correct_count = models.IntegerField(null=True, blank=True)
    score = models.IntegerField(null=True, blank=True)  # 0~100. correct_count / question_count × 100
    created_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'exams'
        ordering = ['id']


class ExamQuestion(models.Model):
    """문항과 답안. 한 시험을 푸는 사람은 한 명이라 답안을 따로 나누지 않는다."""

    class QuestionType(models.TextChoices):
        MULTIPLE_CHOICE = 'multiple_choice'
        SHORT_ANSWER = 'short_answer'

    exam = models.ForeignKey(Exam, on_delete=models.CASCADE, related_name='questions')
    number = models.IntegerField()  # 1부터
    question_type = models.CharField(max_length=20, choices=QuestionType.choices)
    content = models.TextField()
    choices = models.JSONField(null=True, blank=True)  # 객관식 보기 배열. 주관식이면 NULL
    correct_answer = models.TextField()  # 학생 AI에게는 절대 보내지 않음
    explanation = models.TextField()
    # 관련 용어. 보고서의 '관련 오답 N문제'에 씀
    term = models.ForeignKey(Term, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    response = models.TextField(null=True, blank=True)  # 학생 AI(평가) 또는 사용자(재시험)의 답
    is_correct = models.BooleanField(null=True, blank=True)
    answered_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'exam_questions'
        ordering = ['number']
        constraints = [
            models.UniqueConstraint(fields=['exam', 'number'], name='unique_exam_question_number'),
        ]


class Report(models.Model):
    """성장보고서. 수업 1회에 1개. 놓친 개념과 점수 비교는 저장하지 않고 조회할 때 계산한다."""

    lesson = models.OneToOneField(Lesson, on_delete=models.CASCADE, related_name='report')
    score = models.IntegerField()  # 학생 AI 평가 점수 (kind = evaluation 시험의 점수)
    strengths = models.JSONField()  # 잘한 점 문장 배열
    review_recommendations = models.JSONField()  # 복습 추천 [{term_id, text}]
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)  # 재시험 결과 반영 시 갱신

    class Meta:
        db_table = 'reports'
