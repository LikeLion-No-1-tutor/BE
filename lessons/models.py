"""수업. ERD의 lessons, messages, hand_raises, lesson_terms, notes 테이블."""
from django.conf import settings
from django.db import models
from django.utils import timezone

from materials.models import Material, Term
from personas.models import Persona


class Lesson(models.Model):
    """학습 세션 (수업 1회). Django의 session과 헷갈리지 않게 lesson이라고 부른다."""

    class Status(models.TextChoices):
        TEACHING = 'teaching'  # 가르치는 중
        EVALUATING = 'evaluating'  # 종료 후 정리노트·평가·보고서 만드는 중
        COMPLETED = 'completed'
        FAILED = 'failed'

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='lessons')
    material = models.OneToOneField(Material, on_delete=models.CASCADE, related_name='lesson')  # 자료 1개 = 수업 1개
    persona = models.ForeignKey(Persona, on_delete=models.PROTECT, related_name='lessons')
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.TEACHING)
    error = models.JSONField(null=True, blank=True)  # 수업 종료 후 처리 실패 이유 {code, message, request_id}
    started_at = models.DateTimeField(default=timezone.now)
    ended_at = models.DateTimeField(null=True, blank=True)  # '수업 종료'를 누른 시각

    class Meta:
        db_table = 'lessons'

    def __str__(self):
        return f'{self.material.title} ({self.persona.name})'


class Message(models.Model):
    """수업 대화. 학생 AI가 보내는 것은 첫 인사(greeting)와 손 든 표시의 질문(question)뿐."""

    class Sender(models.TextChoices):
        TEACHER = 'teacher'  # 사용자
        STUDENT = 'student'  # 학생 AI

    class Kind(models.TextChoices):
        GREETING = 'greeting'
        EXPLANATION = 'explanation'
        QUESTION = 'question'
        ANSWER = 'answer'

    lesson = models.ForeignKey(Lesson, on_delete=models.CASCADE, related_name='messages')
    sender = models.CharField(max_length=10, choices=Sender.choices)
    kind = models.CharField(max_length=20, choices=Kind.choices)
    content = models.TextField()  # 텍스트만
    # answer가 답한 question
    reply_to = models.ForeignKey('self', on_delete=models.SET_NULL, null=True, blank=True, related_name='replies')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'messages'
        ordering = ['id']


class HandRaise(models.Model):
    """손 든 표시. 손을 든 순간에는 질문을 만들지 않고, 버튼을 누를 때 그때까지의 대화와 reason으로 만든다."""

    class Status(models.TextChoices):
        RAISED = 'raised'  # 손 든 상태
        ASKED = 'asked'  # 질문함

    lesson = models.ForeignKey(Lesson, on_delete=models.CASCADE, related_name='hand_raises')
    # 이 설명을 듣고 손을 듦 (채팅에서 손 버튼이 뜨는 위치)
    after_message = models.ForeignKey(Message, on_delete=models.CASCADE, related_name='+')
    reason = models.TextField()  # 무엇이 궁금한지. 학생 AI 내부용이라 응답으로 내려주지 않음
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.RAISED)
    # 버튼을 눌러 만든 질문 메시지
    question_message = models.OneToOneField(
        Message, on_delete=models.SET_NULL, null=True, blank=True, related_name='hand_raise',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    asked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'hand_raises'
        ordering = ['id']


class LessonTerm(models.Model):
    """실시간 용어 체크. 수업을 시작할 때 자료의 용어 수만큼 todo로 만든다. explained는 다시 내려가지 않는다."""

    class Status(models.TextChoices):
        TODO = 'todo'  # 아직
        MENTIONED = 'mentioned'  # 이름만 언급
        EXPLAINED = 'explained'  # 설명함

    lesson = models.ForeignKey(Lesson, on_delete=models.CASCADE, related_name='lesson_terms')
    term = models.ForeignKey(Term, on_delete=models.CASCADE, related_name='lesson_terms')
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.TODO)
    # 마지막으로 상태를 바꾼 메시지
    message = models.ForeignKey(Message, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'lesson_terms'
        ordering = ['term__display_order', 'term_id']
        constraints = [
            models.UniqueConstraint(fields=['lesson', 'term'], name='unique_lesson_term'),
        ]


class Note(models.Model):
    """정리노트. 수업 1회에 1개."""

    lesson = models.OneToOneField(Lesson, on_delete=models.CASCADE, related_name='note')
    content = models.TextField()  # Markdown
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'notes'
