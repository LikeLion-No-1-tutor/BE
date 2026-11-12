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
        for code in ['haneul', 'minjun', 'seoyeon', 'hyunwoo']:
            material = make_ready_material(self.user, title='RNN')
            persona = Persona.objects.get(code=code)
            body = self.start(material_id=material.id, persona_id=persona.id).json()
            contents.add(body['messages'][0]['content'])
        self.assertEqual(len(contents), 4)

    def test_professor_greeting(self):
        professor = Persona.objects.get(code='hyunwoo')
        body = self.start(persona_id=professor.id).json()
        self.assertEqual(
            body['messages'][0]['content'],
            '안녕하세요, 선생님. 오늘은 word2vec을(를) 처음 배우러 왔습니다. 정의와 근거를 하나씩 여쭤보면서 듣겠습니다.',
        )

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
        self.assertEqual(Persona.objects.count(), 4)  # 페르소나는 남음


class LessonFixture(TestCase):
    """수업을 하나 시작해 둔 상태. 수업 정보·수업 대화 조회 테스트가 같이 쓴다."""

    def setUp(self):
        self.user = make_user()
        self.client = client_for(self.user)
        material = make_ready_material(self.user, title='word2vec', terms=['분산 표현', '원핫 표현', 'CBOW'])
        persona = Persona.objects.get(code='minjun')
        body = self.client.post(URL, {'material_id': material.id, 'persona_id': persona.id}, format='json').json()
        self.lesson = Lesson.objects.get(pk=body['id'])
        self.greeting = self.lesson.messages.get()

    def say(self, content, sender='teacher', kind='explanation', reply_to=None):
        return Message.objects.create(lesson=self.lesson, sender=sender, kind=kind, content=content,
                                      reply_to=reply_to)

    def raise_hand(self, after_message, reason='내부 메모: 이게 왜 그런지 궁금함'):
        return HandRaise.objects.create(lesson=self.lesson, after_message=after_message, reason=reason)

    def set_term(self, name, status):
        LessonTerm.objects.filter(lesson=self.lesson, term__name=name).update(status=status)


class LessonDetailTests(LessonFixture):
    """수업 정보 + 용어 체크리스트 GET /api/lessons/{lesson_id}"""

    def get(self, lesson_id=None, client=None):
        return (client or self.client).get(f'{URL}/{lesson_id or self.lesson.id}')

    def test_new_lesson(self):
        response = self.get()

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body['id'], self.lesson.id)
        self.assertEqual(body['status'], 'teaching')
        self.assertEqual(body['material']['title'], 'word2vec')
        self.assertEqual(body['persona']['name'], '민준')
        self.assertEqual([t['status'] for t in body['terms']], ['todo', 'todo', 'todo'])
        self.assertEqual(body['term_summary'], {'explained': 0, 'total': 3})
        self.assertEqual(body['raised_hand_count'], 0)
        self.assertIsNone(body['note_id'])
        self.assertIsNone(body['report_id'])
        self.assertTrue(body['started_at'].endswith('+09:00'))
        self.assertIsNone(body['ended_at'])

    def test_term_status_and_summary(self):
        self.set_term('분산 표현', 'explained')
        self.set_term('원핫 표현', 'mentioned')

        body = self.get().json()

        self.assertEqual([(t['name'], t['status']) for t in body['terms']],
                         [('분산 표현', 'explained'), ('원핫 표현', 'mentioned'), ('CBOW', 'todo')])
        self.assertEqual(body['term_summary'], {'explained': 1, 'total': 3})

    def test_raised_hand_count_counts_only_raised(self):
        explanation = self.say('word2vec은 ...')
        self.raise_hand(explanation)
        self.raise_hand(explanation)
        asked = self.raise_hand(explanation)
        asked.status = HandRaise.Status.ASKED
        asked.save()

        self.assertEqual(self.get().json()['raised_hand_count'], 2)

    def test_note_and_report_ids(self):
        note = Note.objects.create(lesson=self.lesson, content='# 노트')
        report = Report.objects.create(lesson=self.lesson, score=60, strengths=[], review_recommendations=[])

        body = self.get().json()

        self.assertEqual((body['note_id'], body['report_id']), (note.id, report.id))

    def test_finished_lesson_is_readable(self):
        Lesson.objects.filter(pk=self.lesson.pk).update(status='completed')
        self.assertEqual(self.get().json()['status'], 'completed')

    def test_response_hides_definitions(self):
        self.assertNotIn('의 정의', self.get().content.decode())

    def test_errors(self):
        other = make_user(email='other@gmail.com')
        assert_error(self, self.get(lesson_id=999999), 404, 'NOT_FOUND')
        assert_error(self, self.get(client=client_for(other)), 403, 'FORBIDDEN')
        assert_error(self, self.get(client=APIClient()), 401, 'UNAUTHORIZED')
        assert_error(self, self.get(client=client_for(make_user(email='n@gmail.com', nickname=None))),
                     409, 'NICKNAME_REQUIRED')


class LessonMessagesTests(LessonFixture):
    """수업 대화 + 손 든 표시 GET /api/lessons/{lesson_id}/messages"""

    def get(self, query='', lesson_id=None, client=None):
        return (client or self.client).get(f'{URL}/{lesson_id or self.lesson.id}/messages{query}')

    def test_messages_in_time_order(self):
        explanation = self.say('word2vec은 단어를 벡터로 ...')
        question = self.say('단어 벡터는 어디서 나와요?', sender='student', kind='question')
        answer = self.say('입력층 가중치의 각 행이에요.', kind='answer', reply_to=question)

        body = self.get().json()

        self.assertEqual([m['id'] for m in body['messages']],
                         [self.greeting.id, explanation.id, question.id, answer.id])
        self.assertEqual(body['messages'][3], {
            'id': answer.id, 'sender': 'teacher', 'kind': 'answer', 'content': '입력층 가중치의 각 행이에요.',
            'reply_to_id': question.id, 'created_at': body['messages'][3]['created_at'],
        })
        self.assertTrue(body['messages'][3]['created_at'].endswith('+09:00'))

    def test_hand_raises_without_reason(self):
        explanation = self.say('word2vec은 ...')
        raised = self.raise_hand(explanation)
        question = self.say('질문', sender='student', kind='question')
        asked = self.raise_hand(explanation)
        asked.status, asked.question_message = HandRaise.Status.ASKED, question
        asked.save()

        response = self.get()

        self.assertEqual(response.json()['hand_raises'], [
            {'id': raised.id, 'after_message_id': explanation.id, 'status': 'raised', 'question_message_id': None},
            {'id': asked.id, 'after_message_id': explanation.id, 'status': 'asked',
             'question_message_id': question.id},
        ])
        self.assertNotIn('내부 메모', response.content.decode())

    def test_before_and_limit(self):
        said = [self.say(f'설명 {i}') for i in range(5)]  # 첫 인사 다음에 5개

        latest_two = self.get('?limit=2').json()['messages']
        self.assertEqual([m['id'] for m in latest_two], [said[3].id, said[4].id])

        older = self.get(f'?before={said[3].id}&limit=2').json()['messages']
        self.assertEqual([m['id'] for m in older], [said[1].id, said[2].id])

        oldest = self.get(f'?before={said[1].id}&limit=50').json()['messages']
        self.assertEqual([m['id'] for m in oldest], [self.greeting.id, said[0].id])

    def test_hand_raises_follow_returned_messages(self):
        old = self.say('예전 설명')
        new = self.say('최근 설명')
        self.raise_hand(old)
        recent_hand = self.raise_hand(new)

        body = self.get('?limit=1').json()

        self.assertEqual([m['id'] for m in body['messages']], [new.id])
        self.assertEqual([h['id'] for h in body['hand_raises']], [recent_hand.id])

    def test_limit_is_capped(self):
        self.assertEqual(self.get('?limit=100000').status_code, 200)

    def test_invalid_query_is_400(self):
        for query in ['?before=abc', '?limit=abc', '?limit=0', '?before=-1', '?limit=1.5']:
            with self.subTest(query=query):
                response = self.get(query)
                assert_error(self, response, 400, 'VALIDATION_ERROR')
                self.assertEqual(response.json()['error']['message'], 'before와 limit은 숫자여야 해요.')

    def test_errors(self):
        assert_error(self, self.get(lesson_id=999999), 404, 'NOT_FOUND')
        assert_error(self, self.get(client=client_for(make_user(email='other@gmail.com'))), 403, 'FORBIDDEN')
        assert_error(self, self.get(client=APIClient()), 401, 'UNAUTHORIZED')
