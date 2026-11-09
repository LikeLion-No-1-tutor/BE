from django.db import IntegrityError, transaction
from django.test import TestCase

from common.testing import make_ready_material, make_user
from lessons.models import Lesson
from personas.models import Persona

from .models import Exam, ExamQuestion


class ExamModelTests(TestCase):
    def setUp(self):
        user = make_user()
        material = make_ready_material(user)
        lesson = Lesson.objects.create(user=user, material=material, persona=Persona.objects.first())
        self.exam = Exam.objects.create(lesson=lesson, kind=Exam.Kind.EVALUATION, question_count=2)
        self.term = material.terms.first()

    def question(self, number, **fields):
        fields.setdefault('question_type', ExamQuestion.QuestionType.SHORT_ANSWER)
        return ExamQuestion.objects.create(exam=self.exam, number=number, content='?', correct_answer='!',
                                           explanation='.', **fields)

    def test_new_exam_is_generating(self):
        self.assertEqual(self.exam.status, Exam.Status.GENERATING)
        self.assertIsNone(self.exam.score)

    def test_question_numbers_are_unique_per_exam(self):
        self.question(1)
        with self.assertRaises(IntegrityError), transaction.atomic():
            self.question(1)

    def test_questions_are_ordered_by_number(self):
        self.question(2)
        self.question(1)
        self.assertEqual([q.number for q in self.exam.questions.all()], [1, 2])

    def test_multiple_choice_keeps_choices(self):
        question = self.question(1, question_type=ExamQuestion.QuestionType.MULTIPLE_CHOICE,
                                 choices=['가', '나', '다', '라'], term=self.term)
        question.refresh_from_db()
        self.assertEqual(question.choices, ['가', '나', '다', '라'])
        self.assertEqual(question.term, self.term)
