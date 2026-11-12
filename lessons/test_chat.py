"""설명·답변 보내기, 질문 받기. AI 서버는 requests.post를 바꿔 흉내 낸다."""
import json
from unittest.mock import MagicMock, patch

import requests
from django.test import override_settings
from rest_framework.test import APIClient

from common.testing import client_for, make_ready_material, make_user
from materials.tests import FakeResponse
from personas.models import Persona

from .models import HandRaise, Lesson, LessonTerm, Message
from .tests import URL, LessonFixture, assert_error

USAGE = [{'role': 'judge', 'model': 'm', 'input_tokens': 1, 'output_tokens': 1}]


def analyze_result(term_updates=(), reason=None, reaction=None):
    return {
        'term_updates': [{'term_id': term_id, 'status': value} for term_id, value in term_updates],
        'hand_raise': None if reason is None else {'reason': reason},
        'reaction': reaction,
        'usage': USAGE,
    }


@override_settings(AI_SERVER_URL='http://ai.test', AI_SERVER_TOKEN='internal-token')
class ChatFixture(LessonFixture):
    def setUp(self):
        super().setUp()
        self.terms = {lt.term.name: lt.term for lt in self.lesson.lesson_terms.select_related('term')}
        # self.ai가 돌려주는 값이 AI 서버의 200 응답 본문, 던지는 예외가 통신 실패
        self.ai = MagicMock()
        patcher = patch('common.ai_client.requests.post', lambda *a, **kw: FakeResponse(200, self.ai(*a, **kw)))
        patcher.start()
        self.addCleanup(patcher.stop)

    def sent_payload(self):
        args, kwargs = self.ai.call_args
        return args[0].replace('http://ai.test', ''), kwargs['json']

    def assert_called_once_in_realtime(self):
        self.assertEqual(self.ai.call_count, 1)  # 다시 부르지 않음
        self.assertEqual(self.ai.call_args.kwargs['timeout'], 30)

    def term_status(self, name):
        return LessonTerm.objects.get(lesson=self.lesson, term__name=name).status


class SendMessageTests(ChatFixture):
    """설명·답변 보내기 POST /api/lessons/{lesson_id}/messages"""

    def send(self, content='word2vec에는 CBOW와 스킵그램이 있어.', reply_to_id=None, lesson_id=None, client=None):
        body = {'content': content}
        if reply_to_id is not None:
            body['reply_to_id'] = reply_to_id
        return (client or self.client).post(f'{URL}/{lesson_id or self.lesson.id}/messages', body, format='json')

    # 성공 ---------------------------------------------------------------

    def test_explanation_with_term_updates_and_hand_raise(self):
        self.ai.return_value = analyze_result(
            [(self.terms['CBOW'].id, 'explained'), (self.terms['분산 표현'].id, 'mentioned')],
            reason='CBOW와 스킵그램을 언제 쓰는지 궁금함',
        )

        response = self.send()

        self.assertEqual(response.status_code, 201, response.content)
        body = response.json()
        message = Message.objects.get(lesson=self.lesson, sender='teacher')
        self.assertEqual(body['message'], {
            'id': message.id, 'sender': 'teacher', 'kind': 'explanation',
            'content': 'word2vec에는 CBOW와 스킵그램이 있어.', 'reply_to_id': None,
            'created_at': body['message']['created_at'],
        })
        # 용어는 자료 순서대로, 이름을 붙여서
        self.assertEqual(body['term_updates'], [
            {'term_id': self.terms['분산 표현'].id, 'name': '분산 표현', 'status': 'mentioned'},
            {'term_id': self.terms['CBOW'].id, 'name': 'CBOW', 'status': 'explained'},
        ])
        self.assertEqual(body['term_summary'], {'explained': 1, 'total': 3})
        hand_raise = HandRaise.objects.get()
        self.assertEqual(body['new_hand_raise'], {'id': hand_raise.id, 'after_message_id': message.id,
                                                  'status': 'raised'})
        self.assertEqual(body['raised_hand_count'], 1)
        self.assertIsNone(body['reaction'])
        self.assertNotIn('언제 쓰는지', response.content.decode())  # reason은 내려주지 않음

        self.assertEqual(hand_raise.reason, 'CBOW와 스킵그램을 언제 쓰는지 궁금함')
        cbow = LessonTerm.objects.get(lesson=self.lesson, term=self.terms['CBOW'])
        self.assertEqual((cbow.status, cbow.message), ('explained', message))

    def test_no_hand_raise(self):
        self.ai.return_value = analyze_result()
        body = self.send().json()
        self.assertIsNone(body['new_hand_raise'])
        self.assertEqual(body['term_updates'], [])
        self.assertFalse(HandRaise.objects.exists())

    def test_payload_to_ai(self):
        self.set_term('분산 표현', 'explained')
        explanation = self.say('예전 설명')
        self.raise_hand(explanation, reason='아직 질문 안 한 이유')
        asked = self.raise_hand(explanation, reason='이미 질문한 이유')
        asked.status = 'asked'
        asked.save()
        self.ai.return_value = analyze_result()

        self.send('새 설명')

        path, payload = self.sent_payload()
        self.assertEqual(path, '/lessons/messages/analyze')
        judge, student = payload['judge'], payload['student']
        self.assertEqual(judge['message'], {'kind': 'explanation', 'content': '새 설명'})
        self.assertIsNone(judge['reply_to_question'])
        # explained가 아닌 용어만, 정의와 함께
        self.assertEqual([(t['name'], t['status']) for t in judge['terms']], [('원핫 표현', 'todo'), ('CBOW', 'todo')])
        self.assertEqual(judge['terms'][0]['definition'], '원핫 표현의 정의')

        self.assertEqual(student['persona']['code'], 'minjun')
        self.assertTrue(student['persona']['system_prompt'])
        self.assertEqual([m['content'] for m in student['messages']][-2:], ['예전 설명', '새 설명'])
        self.assertEqual(student['messages'][0]['kind'], 'greeting')
        self.assertEqual(student['messages'][-1], {'id': None, 'sender': 'teacher', 'kind': 'explanation',
                                                   'content': '새 설명', 'reply_to_id': None})
        self.assertEqual(student['raised_reasons'], ['아직 질문 안 한 이유'])

    def test_student_part_never_gets_definitions_or_summary(self):
        self.ai.return_value = analyze_result()
        self.send()
        _, payload = self.sent_payload()
        student_text = json.dumps(payload['student'], ensure_ascii=False)
        self.assertNotIn('의 정의', student_text)
        self.assertNotIn(self.lesson.material.summary, json.dumps(payload, ensure_ascii=False))

    def test_request_id_and_user_are_passed(self):
        self.ai.return_value = analyze_result()
        with self.assertLogs('common.ai_client', level='INFO') as logs:
            response = self.send()
        self.assertEqual(self.ai.call_args.kwargs['headers']['X-Request-ID'], response.headers['X-Request-ID'])
        self.assertEqual(logs.records[0].request_id, response.headers['X-Request-ID'])
        self.assertEqual(logs.records[0].user_id, self.user.id)

    def test_answer_to_question(self):
        question = self.say('단어 벡터는 어디서 나와요?', sender='student', kind='question')
        self.ai.return_value = analyze_result()

        body = self.send('입력층 가중치의 각 행이야.', reply_to_id=question.id).json()

        self.assertEqual((body['message']['kind'], body['message']['reply_to_id']), ('answer', question.id))
        _, payload = self.sent_payload()
        self.assertEqual(payload['judge']['message']['kind'], 'answer')
        self.assertEqual(payload['judge']['reply_to_question'], '단어 벡터는 어디서 나와요?')
        self.assertEqual(payload['student']['messages'][-1]['reply_to_id'], question.id)

    def test_reaction_after_answer_is_shown_but_not_saved(self):
        question = self.say('단어 벡터는 어디서 나와요?', sender='student', kind='question')
        self.ai.return_value = analyze_result(reaction=' 아, 그래서 그런 거였군요! 이유를 들으니까 이해돼요. ')

        body = self.send('입력층 가중치의 각 행이야.', reply_to_id=question.id).json()

        self.assertEqual(body['reaction'], '아, 그래서 그런 거였군요! 이유를 들으니까 이해돼요.')
        # 수업 대화에는 저장하지 않음: 첫 인사, 질문, 방금 보낸 답만
        self.assertEqual(
            list(Message.objects.filter(lesson=self.lesson).values_list('kind', flat=True)),
            ['greeting', 'question', 'answer'],
        )
        messages = self.client.get(f'{URL}/{self.lesson.id}/messages').json()['messages']
        self.assertNotIn('이유를 들으니까', str(messages))
        # 다음 AI 호출의 대화에도 들어가지 않음
        self.ai.return_value = analyze_result()
        self.send('다음 설명')
        _, payload = self.sent_payload()
        self.assertNotIn('이유를 들으니까', str(payload))

    def test_missing_or_blank_reaction_is_null(self):
        for result in [{'term_updates': [], 'hand_raise': None}, analyze_result(reaction='  ')]:
            with self.subTest(result=result):
                self.ai.return_value = result
                self.assertIsNone(self.send().json()['reaction'])

    def test_terms_only_go_up(self):
        self.set_term('분산 표현', 'explained')
        self.set_term('원핫 표현', 'mentioned')
        self.ai.return_value = analyze_result([
            (self.terms['분산 표현'].id, 'mentioned'),  # 내려가는 판정 → 무시
            (self.terms['원핫 표현'].id, 'todo'),  # 내려가는 판정 → 무시
            (self.terms['CBOW'].id, 'mentioned'),  # todo → mentioned
            (999999, 'explained'),  # 이 수업에 없는 용어 → 무시
            (self.terms['CBOW'].id, 'unknown'),  # 모르는 상태 → 무시
        ])

        body = self.send().json()

        self.assertEqual([(t['name'], t['status']) for t in body['term_updates']], [('CBOW', 'mentioned')])
        self.assertEqual(
            [self.term_status(name) for name in ['분산 표현', '원핫 표현', 'CBOW']],
            ['explained', 'mentioned', 'mentioned'],
        )

    def test_content_is_trimmed_and_3000_chars_ok(self):
        self.ai.return_value = analyze_result()
        self.assertEqual(self.send('  설명  ').json()['message']['content'], '설명')
        self.assertEqual(self.send('가' * 3000).status_code, 201)

    # 실패 ---------------------------------------------------------------

    def test_invalid_content_is_400(self):
        for content in ['', '   ', '가' * 3001, None]:
            with self.subTest(length=len(content or '')):
                response = self.client.post(f'{URL}/{self.lesson.id}/messages', {'content': content}, format='json')
                assert_error(self, response, 400, 'VALIDATION_ERROR')
        self.ai.assert_not_called()

    def test_reply_to_must_be_question_of_this_lesson(self):
        explanation = self.say('설명')
        other_user = make_user(email='o@gmail.com')
        other_lesson = Lesson.objects.create(user=other_user, material=make_ready_material(other_user),
                                             persona=Persona.objects.first())
        other_question = Message.objects.create(lesson=other_lesson, sender='student', kind='question', content='?')

        for reply_to_id in [explanation.id, other_question.id, 999999]:
            with self.subTest(reply_to_id=reply_to_id):
                assert_error(self, self.send(reply_to_id=reply_to_id), 400, 'VALIDATION_ERROR')
        self.ai.assert_not_called()

    def test_ai_failure_saves_nothing(self):
        self.ai.side_effect = requests.Timeout()

        response = self.send()

        assert_error(self, response, 502, 'AI_ERROR')
        self.assert_called_once_in_realtime()
        self.assertEqual(response.json()['error']['message'], 'AI 처리에 실패했어요. 다시 시도해 주세요.')
        self.assertEqual(Message.objects.filter(lesson=self.lesson).count(), 1)  # 첫 인사만
        self.assertFalse(HandRaise.objects.exists())

    def test_unexpected_ai_response_saves_nothing(self):
        for result in [{}, {'term_updates': 'x'}, {'term_updates': [{'term_id': 'a'}]},
                       {'term_updates': [], 'hand_raise': 'x'},
                       {'term_updates': [], 'hand_raise': None, 'reaction': ['아하']}]:
            with self.subTest(result=result):
                self.ai.return_value = result
                with self.assertLogs('common.ai_client', level='ERROR') as logs:
                    assert_error(self, self.send(), 502, 'AI_ERROR')
                self.assertIn('INVALID_RESPONSE', logs.output[0])
        self.assertEqual(Message.objects.filter(lesson=self.lesson).count(), 1)

    def test_blank_hand_raise_reason_is_no_hand_raise(self):
        self.ai.return_value = analyze_result(reason='   ')
        self.assertIsNone(self.send().json()['new_hand_raise'])

    def test_finished_lesson_is_409(self):
        Lesson.objects.filter(pk=self.lesson.pk).update(status='evaluating')
        assert_error(self, self.send(), 409, 'LESSON_NOT_TEACHING')
        self.ai.assert_not_called()

    def test_lesson_ended_while_waiting_for_ai(self):
        def end_lesson_then_answer(*args, **kwargs):
            Lesson.objects.filter(pk=self.lesson.pk).update(status='evaluating')
            return analyze_result([(self.terms['CBOW'].id, 'explained')])

        self.ai.side_effect = end_lesson_then_answer

        assert_error(self, self.send(), 409, 'LESSON_NOT_TEACHING')
        self.assertEqual(Message.objects.filter(lesson=self.lesson).count(), 1)
        self.assertEqual(self.term_status('CBOW'), 'todo')

    def test_access_errors(self):
        assert_error(self, self.send(lesson_id=999999), 404, 'NOT_FOUND')
        assert_error(self, self.send(client=client_for(make_user(email='o@gmail.com'))), 403, 'FORBIDDEN')
        assert_error(self, self.send(client=APIClient()), 401, 'UNAUTHORIZED')
        self.ai.assert_not_called()


class AskQuestionTests(ChatFixture):
    """질문 받기 POST /api/lessons/{lesson_id}/hand-raises/{hand_raise_id}/ask"""

    def setUp(self):
        super().setUp()
        self.explanation = self.say('word2vec은 단어를 벡터로 바꾸는 방법이야.')
        self.hand = self.raise_hand(self.explanation, reason='번호만 붙이면 왜 안 되는지 궁금함')
        self.ai.return_value = {'content': ' 단어에 그냥 번호를 붙이면 안 되나요? ', 'usage': USAGE}

    def ask(self, hand_raise_id=None, lesson_id=None, client=None):
        url = f'{URL}/{lesson_id or self.lesson.id}/hand-raises/{hand_raise_id or self.hand.id}/ask'
        return (client or self.client).post(url)

    def test_ask(self):
        self.raise_hand(self.explanation, reason='다른 궁금증')

        response = self.ask()

        self.assertEqual(response.status_code, 201, response.content)
        body = response.json()
        question = Message.objects.get(kind='question')
        self.assertEqual(body['hand_raise'], {'id': self.hand.id, 'after_message_id': self.explanation.id,
                                              'status': 'asked', 'question_message_id': question.id})
        self.assertEqual(body['question'], {
            'id': question.id, 'sender': 'student', 'kind': 'question',
            'content': '단어에 그냥 번호를 붙이면 안 되나요?', 'created_at': body['question']['created_at'],
        })
        self.assertEqual(body['raised_hand_count'], 1)
        self.assertNotIn('궁금함', response.content.decode())

        self.hand.refresh_from_db()
        self.assertEqual((self.hand.status, self.hand.question_message), ('asked', question))
        self.assertIsNotNone(self.hand.asked_at)

    def test_payload_has_conversation_up_to_now(self):
        self.say('손 든 뒤에 더 한 설명')

        self.ask()

        path, payload = self.sent_payload()
        self.assertEqual(path, '/lessons/questions')
        self.assertEqual(payload['persona']['code'], 'minjun')
        self.assertEqual([m['content'] for m in payload['messages']][1:],
                         ['word2vec은 단어를 벡터로 바꾸는 방법이야.', '손 든 뒤에 더 한 설명'])
        self.assertEqual(payload['reason'], '번호만 붙이면 왜 안 되는지 궁금함')
        self.assertNotIn('의 정의', json.dumps(payload, ensure_ascii=False))
        self.assertNotIn(self.lesson.material.summary, json.dumps(payload, ensure_ascii=False))

    def test_already_asked_is_409(self):
        self.assertEqual(self.ask().status_code, 201)
        self.ai.reset_mock()
        assert_error(self, self.ask(), 409, 'HAND_ALREADY_ASKED')
        self.ai.assert_not_called()

    def test_double_click_while_waiting_for_ai(self):
        def other_click_finishes_first(*args, **kwargs):
            HandRaise.objects.filter(pk=self.hand.pk).update(status='asked')
            return {'content': '질문', 'usage': USAGE}

        self.ai.side_effect = other_click_finishes_first

        assert_error(self, self.ask(), 409, 'HAND_ALREADY_ASKED')
        self.assertFalse(Message.objects.filter(kind='question').exists())

    def test_hand_raise_of_other_lesson_is_404(self):
        other_user = make_user(email='o@gmail.com')
        other_lesson = Lesson.objects.create(user=other_user, material=make_ready_material(other_user),
                                             persona=Persona.objects.first())
        other_message = Message.objects.create(lesson=other_lesson, sender='teacher', kind='explanation', content='.')
        other_hand = HandRaise.objects.create(lesson=other_lesson, after_message=other_message, reason='.')

        for hand_raise_id in [other_hand.id, 999999]:
            with self.subTest(hand_raise_id=hand_raise_id):
                response = self.ask(hand_raise_id=hand_raise_id)
                assert_error(self, response, 404, 'NOT_FOUND')
                self.assertEqual(response.json()['error']['message'], '손 든 표시를 찾을 수 없어요.')

    def test_finished_lesson_is_409(self):
        Lesson.objects.filter(pk=self.lesson.pk).update(status='completed')
        assert_error(self, self.ask(), 409, 'LESSON_NOT_TEACHING')
        self.ai.assert_not_called()

    def test_ai_failure_keeps_hand_raised(self):
        self.ai.side_effect = requests.ConnectionError()

        assert_error(self, self.ask(), 502, 'AI_ERROR')
        self.assert_called_once_in_realtime()

        self.hand.refresh_from_db()
        self.assertEqual(self.hand.status, 'raised')
        self.assertFalse(Message.objects.filter(kind='question').exists())

    def test_empty_question_from_ai_is_502(self):
        for result in [{'content': '  '}, {'content': None}, {}]:
            with self.subTest(result=result):
                self.ai.return_value = result
                with self.assertLogs('common.ai_client', level='ERROR') as logs:
                    assert_error(self, self.ask(), 502, 'AI_ERROR')
                self.assertIn('INVALID_RESPONSE', logs.output[0])
        self.hand.refresh_from_db()
        self.assertEqual(self.hand.status, 'raised')

    def test_access_errors(self):
        assert_error(self, self.ask(lesson_id=999999), 404, 'NOT_FOUND')
        assert_error(self, self.ask(client=client_for(make_user(email='o@gmail.com'))), 403, 'FORBIDDEN')
        assert_error(self, self.ask(client=APIClient()), 401, 'UNAUTHORIZED')
