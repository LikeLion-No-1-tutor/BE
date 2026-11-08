from django.db import IntegrityError, transaction
from django.db.models import ProtectedError
from django.test import TestCase
from rest_framework.test import APIClient

from common.testing import client_for, make_ready_material, make_user
from exams.models import Exam, ExamQuestion, Report
from materials.models import Material
from personas.models import Persona

from .models import HandRaise, Lesson, LessonTerm, Message, Note

URL = '/api/lessons'


def assert_error(test, response, http_status, code):
    test.assertEqual(response.status_code, http_status, response.content)
    test.assertEqual(response.json()['error']['code'], code)


class LessonStartTests(TestCase):
    """수업 시작 POST /api/lessons"""

    @classmethod
    def setUpTestData(cls):
        cls.minjun = Persona.objects.get(code='minjun')

    def setUp(self):
        self.user = make_user()
        self.client = client_for(self.user)
        self.material = make_ready_material(self.user, title='word2vec', terms=['분산 표현', '원핫 표현', 'CBOW'])

    def start(self, material_id=None, persona_id=None, client=None):
        body = {
            'material_id': self.material.id if material_id is None else material_id,
            'persona_id': self.minjun.id if persona_id is None else persona_id,
        }
        return (client or self.client).post(URL, body, format='json')

    # 성공 ---------------------------------------------------------------

    def test_start_lesson(self):
        response = self.start()

        self.assertEqual(response.status_code, 201)
        body = response.json()
        lesson = Lesson.objects.get()
        self.assertEqual(body['id'], lesson.id)
        self.assertEqual(body['status'], 'teaching')
        self.assertEqual(body['material'], {'id': self.material.id, 'title': 'word2vec'})
        self.assertEqual(body['persona'], {'id': self.minjun.id, 'name': '민준', 'grade_label': '고1'})
        self.assertEqual(
            [(t['name'], t['status']) for t in body['terms']],
            [('분산 표현', 'todo'), ('원핫 표현', 'todo'), ('CBOW', 'todo')],
        )
        self.assertEqual([t['term_id'] for t in body['terms']],
                         list(self.material.terms.values_list('id', flat=True)))

    def test_greeting_message(self):
        body = self.start().json()

        self.assertEqual(len(body['messages']), 1)
        greeting = body['messages'][0]
        self.assertEqual(set(greeting), {'id', 'sender', 'kind', 'content', 'created_at'})
        self.assertEqual((greeting['sender'], greeting['kind']), ('student', 'greeting'))
        self.assertIn('word2vec', greeting['content'])
        self.assertTrue(greeting['created_at'].endswith('+09:00'))  # 한국 시간

    def test_greeting_differs_by_persona(self):
        contents = set()
        for code in ['haneul', 'minjun', 'seoyeon']:
            material = make_ready_material(self.user, title='RNN')
            persona = Persona.objects.get(code=code)
            body = self.start(material_id=material.id, persona_id=persona.id).json()
            contents.add(body['messages'][0]['content'])
        self.assertEqual(len(contents), 3)

    def test_rows_are_saved(self):
        self.start()

        lesson = Lesson.objects.get()
        self.assertEqual((lesson.user, lesson.material, lesson.persona), (self.user, self.material, self.minjun))
        self.assertIsNotNone(lesson.started_at)
        self.assertIsNone(lesson.ended_at)
        self.assertEqual(LessonTerm.objects.filter(lesson=lesson, status='todo').count(), 3)
        self.assertEqual(Message.objects.filter(lesson=lesson).count(), 1)

    def test_material_without_terms(self):
        material = make_ready_material(self.user, terms=[])
        response = self.start(material_id=material.id)
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()['terms'], [])

    def test_response_hides_definitions_and_summary(self):
        text = self.start().content.decode()
        self.assertNotIn('의 정의', text)  # make_ready_material의 용어 정의
        self.assertNotIn(self.material.summary, text)

    # 에러 ---------------------------------------------------------------

    def test_missing_fields_are_400(self):
        for body in [{}, {'material_id': self.material.id}, {'persona_id': self.minjun.id},
                     {'material_id': 'abc', 'persona_id': self.minjun.id}]:
            with self.subTest(body=body):
                assert_error(self, self.client.post(URL, body, format='json'), 400, 'VALIDATION_ERROR')

    def test_unknown_material_is_404(self):
        assert_error(self, self.start(material_id=999999), 404, 'NOT_FOUND')

    def test_other_users_material_is_403(self):
        other_material = make_ready_material(make_user(email='other@gmail.com'))
        assert_error(self, self.start(material_id=other_material.id), 403, 'FORBIDDEN')
        self.assertFalse(Lesson.objects.exists())

    def test_unknown_persona_is_404(self):
        response = self.start(persona_id=999999)
        assert_error(self, response, 404, 'NOT_FOUND')
        self.assertEqual(response.json()['error']['message'], '페르소나를 찾을 수 없어요.')

    def test_material_not_ready_is_409(self):
        for material_status in [Material.Status.PROCESSING, Material.Status.FAILED]:
            with self.subTest(status=material_status):
                Material.objects.filter(pk=self.material.pk).update(status=material_status)
                assert_error(self, self.start(), 409, 'MATERIAL_NOT_READY')
        self.assertFalse(Lesson.objects.exists())

    def test_material_already_used_is_409(self):
        self.assertEqual(self.start().status_code, 201)
        assert_error(self, self.start(), 409, 'MATERIAL_ALREADY_USED')
        self.assertEqual(Lesson.objects.count(), 1)
        self.assertEqual(Message.objects.count(), 1)

    def test_not_logged_in_is_401(self):
        assert_error(self, self.start(client=APIClient()), 401, 'UNAUTHORIZED')

    def test_nickname_required_is_409(self):
        user = make_user(email='new@gmail.com', nickname=None)
        material = make_ready_material(user)
        assert_error(self, self.start(material_id=material.id, client=client_for(user)), 409, 'NICKNAME_REQUIRED')


class LessonModelTests(TestCase):
    """ERD의 제약과 삭제 정책."""

    def setUp(self):
        self.user = make_user()
        self.material = make_ready_material(self.user)
        self.persona = Persona.objects.get(code='haneul')
        self.lesson = Lesson.objects.create(user=self.user, material=self.material, persona=self.persona)

    def test_one_lesson_per_material(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            Lesson.objects.create(user=self.user, material=self.material, persona=self.persona)

    def test_one_lesson_term_per_term(self):
        term = self.material.terms.first()
        LessonTerm.objects.create(lesson=self.lesson, term=term)
        with self.assertRaises(IntegrityError), transaction.atomic():
            LessonTerm.objects.create(lesson=self.lesson, term=term)

    def test_persona_in_use_cannot_be_deleted(self):
        with self.assertRaises(ProtectedError):
            self.persona.delete()

    def test_deleting_user_deletes_everything_under_lesson(self):
        message = Message.objects.create(lesson=self.lesson, sender='teacher', kind='explanation', content='...')
        HandRaise.objects.create(lesson=self.lesson, after_message=message, reason='...')
        LessonTerm.objects.create(lesson=self.lesson, term=self.material.terms.first(), message=message)
        Note.objects.create(lesson=self.lesson, content='# 노트')
        exam = Exam.objects.create(lesson=self.lesson, kind='evaluation', question_count=1)
        ExamQuestion.objects.create(exam=exam, number=1, question_type='short_answer', content='?',
                                    correct_answer='!', explanation='.', term=self.material.terms.first())
        Report.objects.create(lesson=self.lesson, score=100, strengths=[], review_recommendations=[])

        self.user.delete()

        for model in [Lesson, Message, HandRaise, LessonTerm, Note, Exam, ExamQuestion, Report, Material]:
            with self.subTest(model=model.__name__):
                self.assertFalse(model.objects.exists())
        self.assertEqual(Persona.objects.count(), 3)
