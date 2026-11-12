"""재시험 출제, 재시험 문제·상태, 문제 풀이 및 채점, 재시험 결과 저장"""
import json
from unittest.mock import Mock, patch

from django.test import TestCase, override_settings
from django_tasks_db.models import DBTaskResult
from rest_framework.test import APIClient

from common.testing import client_for, make_user
from lessons.models import LessonTerm
from materials.tests import IMMEDIATE_TASKS

from .models import Exam, ExamQuestion, Report
from .retest import run_retest_generate
from .test_reports import add_exam, add_report, assert_error, make_lesson


def http(status_code, body):
    response = Mock()
    response.status_code = status_code
    response.ok = 200 <= status_code < 300
    response.json.return_value = body
    return response


def generated(term_ids):
    return {'questions': [
        {'number': 1, 'question_type': 'multiple_choice', 'content': '원핫 표현의 단점은?',
         'choices': ['차원이 큼', '없음', '모름'], 'correct_answer': '0', 'explanation': '해설1',
         'term_id': term_ids['원핫 표현']},
        {'number': 2, 'question_type': 'short_answer', 'content': 'CBOW를 설명하세요.', 'choices': None,
         'correct_answer': '주변 단어로 가운데 단어를 맞힘', 'explanation': '해설2', 'term_id': term_ids['CBOW']},
        {'number': 3, 'question_type': 'multiple_choice', 'content': '분산 표현은?',
         'choices': ['실수 벡터', '정수'], 'correct_answer': '0', 'explanation': '해설3', 'term_id': None},
    ], 'usage': []}


@override_settings(AI_SERVER_URL='http://ai.test', AI_SERVER_TOKEN='t')
class RetestFixture(TestCase):
    def setUp(self):
        self.user = make_user()
        self.client = client_for(self.user)
        self.lesson = make_lesson(self.user, 'word2vec', day=1)
        LessonTerm.objects.filter(lesson=self.lesson, term__name='분산 표현').update(status='explained')
        self.evaluation = add_exam(self.lesson, 'evaluation', 50, minutes=30,
                                   results=[(True, '분산 표현'), (False, 'CBOW')])
        self.report = add_report(self.lesson, 50)
        self.term_ids = {t.name: t.id for t in self.lesson.material.terms.all()}
        self.post = patch('common.ai_client.requests.post')
        self.ai = self.post.start()
        self.addCleanup(self.post.stop)

    def ai_payload(self):
        return self.ai.call_args.kwargs['json']

    def solving_retest(self):
        """출제가 끝난 재시험 (객관식 1·3번, 주관식 2번)."""
        exam = Exam.objects.create(lesson=self.lesson, kind='retest', status='solving', question_count=3)
        for q in generated(self.term_ids)['questions']:
            fields = {**q, 'term_id': q['term_id']}
            ExamQuestion.objects.create(exam=exam, **fields)
        return exam


class RetestStartTests(RetestFixture):
    """재시험 출제 POST /api/reports/{report_id}/retests"""

    def start(self, body=None, report_id=None, client=None):
        return (client or self.client).post(f'/api/reports/{report_id or self.report.id}/retests',
                                            body or {}, format='json')

    @override_settings(RETEST_QUESTION_COUNT=4, EVALUATION_QUESTION_COUNT=7)
    def test_question_count_follows_retest_setting(self):
        self.assertEqual(self.start().status_code, 202)
        self.assertEqual(Exam.objects.get(kind='retest').question_count, 4)

    def test_start_enqueues_job(self):
        with self.captureOnCommitCallbacks(execute=True):
            response = self.start({'focus': 'all'})

        self.assertEqual(response.status_code, 202, response.content)
        exam = Exam.objects.get(kind='retest')
        self.assertEqual(response.json(), {'id': exam.id, 'status': 'generating'})
        self.assertEqual((exam.lesson, exam.question_count), (self.lesson, 3))  # 평가(5문항)와 따로
        job = DBTaskResult.objects.get()
        self.assertEqual(job.task_path, 'common.jobs.run_job')
        self.assertEqual(job.args_kwargs['args'], [
            'exams.retest.run_retest_generate', [exam.id, 'all', response.headers['X-Request-ID']],
        ])
        self.ai.assert_not_called()

    def test_focus_defaults_to_missed_terms(self):
        with self.captureOnCommitCallbacks(execute=True):
            self.start()
        self.assertEqual(DBTaskResult.objects.get().args_kwargs['args'][1][1], 'missed_terms')

    def test_invalid_focus_is_400(self):
        assert_error(self, self.start({'focus': 'abc'}), 400, 'VALIDATION_ERROR')
        self.assertFalse(Exam.objects.filter(kind='retest').exists())

    def test_generating_retest_blocks_new_one(self):
        self.assertEqual(self.start().status_code, 202)
        assert_error(self, self.start(), 409, 'RETEST_GENERATING')
        self.assertEqual(Exam.objects.filter(kind='retest').count(), 1)

    def test_solving_retest_does_not_block(self):
        self.solving_retest()
        self.assertEqual(self.start().status_code, 202)

    @override_settings(TASKS=IMMEDIATE_TASKS)
    def test_end_to_end_with_immediate_backend(self):
        self.ai.return_value = http(200, generated(self.term_ids))
        with self.assertLogs('exams.retest', level='INFO'), self.captureOnCommitCallbacks(execute=True):
            response = self.start()
        exam = Exam.objects.get(pk=response.json()['id'])
        self.assertEqual((exam.status, exam.question_count), ('solving', 3))

    def test_access_errors(self):
        assert_error(self, self.start(report_id=999999), 404, 'NOT_FOUND')
        assert_error(self, self.start(client=client_for(make_user(email='o@gmail.com'))), 403, 'FORBIDDEN')
        assert_error(self, self.start(client=APIClient()), 401, 'UNAUTHORIZED')


class RetestGenerateTests(RetestFixture):
    """백그라운드 처리 run_retest_generate"""

    def make_generating(self):
        return Exam.objects.create(lesson=self.lesson, kind='retest', status='generating', question_count=3)

    def run_job(self, exam, focus='missed_terms'):
        with self.assertLogs('exams.retest', level='INFO') as logs:
            run_retest_generate(exam.id, focus, 'rid-retest')
        exam.refresh_from_db()
        return logs

    def test_generate(self):
        self.ai.return_value = http(200, generated(self.term_ids))
        exam = self.make_generating()

        logs = self.run_job(exam)

        self.assertEqual((exam.status, exam.question_count), ('solving', 3))
        self.assertEqual([q.number for q in exam.questions.all()], [1, 2, 3])
        self.assertEqual([r.event for r in logs.records], ['job_started', 'job_finished'])
        url = self.ai.call_args.args[0]
        self.assertEqual(url, 'http://ai.test/exams/generate')
        self.assertEqual(self.ai.call_args.kwargs['headers']['X-Request-ID'], 'rid-retest')

    def test_payload_missed_terms(self):
        self.ai.return_value = http(200, generated(self.term_ids))
        self.run_job(self.make_generating(), focus='missed_terms')

        payload = self.ai_payload()
        self.assertEqual((payload['kind'], payload['count']), ('retest', 3))
        self.assertEqual(payload['summary'], self.lesson.material.summary)
        # explained가 아닌 용어 (원핫 표현, CBOW)
        self.assertEqual(payload['focus_term_ids'], [self.term_ids['원핫 표현'], self.term_ids['CBOW']])
        # 이 수업에서 이미 낸 문제는 빼 달라고
        self.assertEqual(payload['exclude_questions'], ['Q1', 'Q2'])

    def test_exclude_questions_keeps_latest_200(self):
        self.ai.return_value = http(200, generated(self.term_ids))
        older = Exam.objects.create(lesson=self.lesson, kind='retest', status='completed', question_count=250)
        ExamQuestion.objects.bulk_create(
            ExamQuestion(exam=older, number=n, question_type='short_answer', content=f'older-{n}',
                         correct_answer='!', explanation='.')
            for n in range(1, 251)
        )

        self.run_job(self.make_generating(), focus='all')

        excluded = self.ai_payload()['exclude_questions']
        self.assertEqual(len(excluded), 200)
        self.assertEqual((excluded[0], excluded[-1]), ('older-51', 'older-250'))

    def test_payload_all(self):
        self.ai.return_value = http(200, generated(self.term_ids))
        self.run_job(self.make_generating(), focus='all')
        self.assertEqual(self.ai_payload()['focus_term_ids'], [])

    def test_failure_is_retried_then_failed(self):
        self.ai.return_value = http(504, {'error': {'code': 'LLM_TIMEOUT', 'message': '...'}})
        exam = self.make_generating()

        with self.assertLogs('common.ai_client', level='WARNING'):
            logs = self.run_job(exam)

        self.assertEqual(self.ai.call_count, 2)
        self.assertEqual(exam.status, 'failed')
        self.assertEqual(exam.error, {'code': 'AI_ERROR', 'message': 'AI 처리에 실패했어요.', 'request_id': 'rid-retest'})
        self.assertFalse(exam.questions.exists())
        self.assertEqual((logs.records[-1].event, logs.records[-1].error_code), ('job_failed', 'LLM_TIMEOUT'))

    def test_bad_shape_is_retried(self):
        self.ai.side_effect = [http(200, {'questions': []}), http(200, generated(self.term_ids))]
        exam = self.make_generating()
        with self.assertLogs('common.ai_client', level='WARNING'):
            self.run_job(exam)
        self.assertEqual(exam.status, 'solving')

    def test_skips_exam_that_is_not_generating(self):
        exam = self.solving_retest()
        with self.assertLogs('exams.retest', level='WARNING'):
            run_retest_generate(exam.id, 'all', 'rid')
        with self.assertLogs('exams.retest', level='WARNING'):
            run_retest_generate(self.evaluation.id, 'all', 'rid')  # 평가 시험은 재시험이 아님
        self.ai.assert_not_called()


class RetestDetailTests(RetestFixture):
    """재시험 문제·상태 GET /api/retests/{retest_id}"""

    def get(self, retest_id, client=None):
        return (client or self.client).get(f'/api/retests/{retest_id}')

    def test_generating(self):
        exam = Exam.objects.create(lesson=self.lesson, kind='retest', status='generating', question_count=10)
        self.assertEqual(self.get(exam.id).json(), {
            'id': exam.id, 'report_id': self.report.id, 'status': 'generating', 'total': 10, 'error': None,
            'questions': [],
        })

    def test_solving_hides_answers_until_answered(self):
        exam = self.solving_retest()
        ExamQuestion.objects.filter(exam=exam, number=1).update(response='1', is_correct=False)

        body = self.get(exam.id).json()

        self.assertEqual((body['status'], body['total']), ('solving', 3))
        first, second = body['questions'][0], body['questions'][1]
        self.assertEqual(first, {
            'number': 1, 'question_type': 'multiple_choice', 'content': '원핫 표현의 단점은?',
            'choices': ['차원이 큼', '없음', '모름'], 'answered': True,
            'response': '1', 'is_correct': False, 'correct_answer': '0', 'explanation': '해설1',
        })
        self.assertEqual(second, {
            'number': 2, 'question_type': 'short_answer', 'content': 'CBOW를 설명하세요.', 'choices': None,
            'answered': False,
        })
        text = json.dumps(body, ensure_ascii=False)
        self.assertNotIn('해설2', text)
        self.assertNotIn('주변 단어로 가운데 단어를 맞힘', text)

    def test_failed_shows_error(self):
        error = {'code': 'AI_ERROR', 'message': 'AI 처리에 실패했어요.', 'request_id': 'r'}
        exam = Exam.objects.create(lesson=self.lesson, kind='retest', status='failed', question_count=10, error=error)
        self.assertEqual(self.get(exam.id).json()['error'], error)

    def test_errors(self):
        exam = self.solving_retest()
        assert_error(self, self.get(999999), 404, 'NOT_FOUND')
        assert_error(self, self.get(self.evaluation.id), 404, 'NOT_FOUND')  # 평가 시험 ID는 안 됨
        assert_error(self, self.get(exam.id, client=client_for(make_user(email='o@gmail.com'))), 403, 'FORBIDDEN')
        assert_error(self, self.get(exam.id, client=APIClient()), 401, 'UNAUTHORIZED')


class RetestAnswerTests(RetestFixture):
    """문제 풀이 및 채점 POST /api/retests/{retest_id}/questions/{number}/answer"""

    def setUp(self):
        super().setUp()
        self.exam = self.solving_retest()

    def answer(self, number, response, exam_id=None, client=None):
        return (client or self.client).post(f'/api/retests/{exam_id or self.exam.id}/questions/{number}/answer',
                                            {'response': response}, format='json')

    def saved(self, number):
        return ExamQuestion.objects.get(exam=self.exam, number=number)

    def test_multiple_choice_is_graded_without_ai(self):
        response = self.answer(1, '0')

        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json(), {'number': 1, 'is_correct': True, 'correct_answer': '0',
                                           'explanation': '해설1'})
        self.assertEqual(self.answer(3, '1').json()['is_correct'], False)
        self.ai.assert_not_called()
        question = self.saved(1)
        self.assertEqual((question.response, question.is_correct), ('0', True))
        self.assertIsNotNone(question.answered_at)

    def test_short_answer_is_graded_by_ai(self):
        self.ai.return_value = http(200, {'results': [{'number': 2, 'is_correct': True, 'reason': '맞음'}],
                                          'usage': []})

        response = self.answer(2, '  주변 단어들로 가운데를 맞혀요  ')

        self.assertEqual(response.json(), {'number': 2, 'is_correct': True,
                                           'correct_answer': '주변 단어로 가운데 단어를 맞힘', 'explanation': '해설2'})
        self.assertEqual(self.ai.call_args.args[0], 'http://ai.test/exams/grade')
        self.assertEqual(self.ai.call_args.kwargs['timeout'], 30)  # 실시간
        self.assertEqual(self.ai_payload(), {'items': [{
            'number': 2, 'content': 'CBOW를 설명하세요.', 'correct_answer': '주변 단어로 가운데 단어를 맞힘',
            'explanation': '해설2', 'response': '주변 단어들로 가운데를 맞혀요',
        }]})
        self.assertEqual(self.saved(2).response, '주변 단어들로 가운데를 맞혀요')

    def test_ai_failure_saves_nothing(self):
        self.ai.return_value = http(502, {'error': {'code': 'LLM_ERROR', 'message': '...'}})
        with self.assertLogs('common.ai_client', level='ERROR'):
            assert_error(self, self.answer(2, '답'), 502, 'AI_ERROR')
        self.assertEqual(self.ai.call_count, 1)  # 실시간은 다시 부르지 않음
        self.assertIsNone(self.saved(2).response)

    def test_invalid_responses_are_400(self):
        for number, value in [(1, ''), (1, '   '), (1, '3'), (1, '-1'), (1, '가'), (2, ''), (2, None), (2, '가' * 3001)]:
            with self.subTest(number=number, value=value):
                assert_error(self, self.answer(number, value), 400, 'VALIDATION_ERROR')
        self.ai.assert_not_called()

    def test_already_answered_is_409(self):
        self.answer(1, '0')
        assert_error(self, self.answer(1, '1'), 409, 'QUESTION_ALREADY_ANSWERED')
        self.assertEqual(self.saved(1).response, '0')

    def test_number_out_of_range_is_404(self):
        for number in [0, 4, 99]:
            with self.subTest(number=number):
                response = self.answer(number, '0')
                assert_error(self, response, 404, 'NOT_FOUND')
                self.assertEqual(response.json()['error']['message'], '없는 문제 번호예요.')

    def test_not_solving_is_409(self):
        for exam_status in ['generating', 'completed', 'failed']:
            with self.subTest(status=exam_status):
                Exam.objects.filter(pk=self.exam.pk).update(status=exam_status)
                assert_error(self, self.answer(1, '0'), 409, 'RETEST_NOT_SOLVING')

    def test_completed_while_waiting_for_ai(self):
        def complete_then_grade(*args, **kwargs):
            Exam.objects.filter(pk=self.exam.pk).update(status='completed')
            return http(200, {'results': [{'number': 2, 'is_correct': True}], 'usage': []})

        self.ai.side_effect = complete_then_grade
        assert_error(self, self.answer(2, '답'), 409, 'RETEST_NOT_SOLVING')
        self.assertIsNone(self.saved(2).response)

    def test_errors(self):
        assert_error(self, self.answer(1, '0', exam_id=999999), 404, 'NOT_FOUND')
        assert_error(self, self.answer(1, '0', client=client_for(make_user(email='o@gmail.com'))), 403, 'FORBIDDEN')
        assert_error(self, self.answer(1, '0', client=APIClient()), 401, 'UNAUTHORIZED')


class RetestCompleteTests(RetestFixture):
    """재시험 결과 저장 POST /api/retests/{retest_id}/complete"""

    def setUp(self):
        super().setUp()
        self.exam = self.solving_retest()

    def complete(self, exam_id=None, client=None):
        return (client or self.client).post(f'/api/retests/{exam_id or self.exam.id}/complete')

    def test_complete(self):
        ExamQuestion.objects.filter(exam=self.exam, number=1).update(response='0', is_correct=True)
        ExamQuestion.objects.filter(exam=self.exam, number=2).update(response='답', is_correct=True)
        before = Report.objects.get(pk=self.report.pk).updated_at

        response = self.complete()

        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json(), {'id': self.exam.id, 'status': 'completed', 'correct': 2, 'total': 3,
                                           'score': 67, 'report_id': self.report.id})
        self.exam.refresh_from_db()
        self.assertEqual((self.exam.status, self.exam.score, self.exam.correct_count), ('completed', 67, 2))
        self.assertIsNotNone(self.exam.completed_at)
        unanswered = ExamQuestion.objects.get(exam=self.exam, number=3)
        self.assertEqual((unanswered.response, unanswered.is_correct), (None, False))  # 답하지 않음 → 오답
        self.assertGreater(Report.objects.get(pk=self.report.pk).updated_at, before)

    def test_result_shows_in_report(self):
        ExamQuestion.objects.filter(exam=self.exam).update(response='0', is_correct=True)
        self.complete()

        body = self.client.get(f'/api/reports/{self.report.id}').json()

        self.assertEqual([h['score'] for h in body['score_history']], [50, 100])
        self.assertEqual(body['comparison'], {'current_score': 100, 'previous_score': 50, 'diff': 50})
        lessons = self.client.get('/api/lessons').json()['items']
        self.assertEqual((lessons[0]['score'], lessons[0]['latest_score']), (50, 100))

    def test_nothing_answered_is_zero(self):
        self.assertEqual(self.complete().json()['score'], 0)

    def test_second_complete_is_409(self):
        self.assertEqual(self.complete().status_code, 200)
        assert_error(self, self.complete(), 409, 'RETEST_NOT_SOLVING')
        self.assertEqual(Exam.objects.filter(kind='retest', status='completed').count(), 1)

    def test_generating_is_409(self):
        Exam.objects.filter(pk=self.exam.pk).update(status='generating')
        assert_error(self, self.complete(), 409, 'RETEST_NOT_SOLVING')

    def test_answer_after_complete_is_409(self):
        self.complete()
        assert_error(self, self.client.post(f'/api/retests/{self.exam.id}/questions/1/answer',
                                            {'response': '0'}, format='json'), 409, 'RETEST_NOT_SOLVING')

    def test_errors(self):
        assert_error(self, self.complete(exam_id=999999), 404, 'NOT_FOUND')
        assert_error(self, self.complete(client=client_for(make_user(email='o@gmail.com'))), 403, 'FORBIDDEN')
        assert_error(self, self.complete(client=APIClient()), 401, 'UNAUTHORIZED')
