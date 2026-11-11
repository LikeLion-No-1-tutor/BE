"""수업 종료, 진행 상태, 정리노트와 백그라운드 처리 lesson_finish.

AI 서버는 requests.post를 가짜 서버(FakeAIServer)로 바꿔 대신한다.
그래서 ai_client의 재시도·응답 확인까지 같이 확인된다.
"""
import json
from unittest.mock import Mock, patch

from django.test import override_settings
from django_tasks_db.models import DBTaskResult
from rest_framework.test import APIClient

from common.testing import client_for, make_user
from exams.models import Exam, ExamQuestion, Report
from materials.tests import IMMEDIATE_TASKS

from .finish import run_lesson_finish
from .models import HandRaise, Lesson, Note
from .tests import URL, LessonFixture, assert_error

USAGE = [{'role': 'x', 'model': 'm', 'input_tokens': 10, 'output_tokens': 5}]


def http(status_code, body):
    response = Mock()
    response.status_code = status_code
    response.ok = 200 <= status_code < 300
    response.json.return_value = body
    return response


class FakeAIServer:
    """경로별로 정해 둔 응답을 돌려주는 가짜 AI 서버. 응답 자리에 list를 주면 차례로 쓴다."""

    def __init__(self, term_ids):
        cbow, onehot = term_ids['CBOW'], term_ids['원핫 표현']
        self.responses = {
            '/lessons/note': {'content': '# word2vec 정리노트\n\n선생님이 말씀하셨다.'},
            '/exams/generate': {'questions': [
                {'number': 1, 'question_type': 'multiple_choice', 'content': 'CBOW가 맞히는 것은?',
                 'choices': ['가운데 단어', '주변 단어'], 'correct_answer': '0', 'explanation': '해설1',
                 'term_id': cbow},
                {'number': 2, 'question_type': 'multiple_choice', 'content': '원핫 표현의 단점은?',
                 'choices': ['차원이 큼', '없음'], 'correct_answer': '0', 'explanation': '해설2',
                 'term_id': onehot},
                {'number': 3, 'question_type': 'short_answer', 'content': '분산 표현을 설명하세요.',
                 'choices': None, 'correct_answer': '실수 벡터로 나타냄', 'explanation': '해설3',
                 'term_id': 999999},  # 요청에 없던 용어 → NULL
            ]},
            '/exams/solve': {'answers': [
                {'number': 1, 'response': '0'},
                {'number': 2, 'response': '1'},
                {'number': 3, 'response': '단어를 벡터로 나타내요.'},
            ]},
            '/exams/grade': {'results': [{'number': 3, 'is_correct': True, 'reason': '핵심을 씀'}]},
            '/reports/generate': {
                'strengths': ['원핫 표현에서 분산 표현으로 자연스럽게 이어 갔어요.'],
                'review_recommendations': [
                    {'term_id': onehot, 'text': '원핫 표현의 단점을 다시 보세요.'},
                    {'term_id': 999999, 'text': '없는 용어 → 버림'},
                ],
            },
        }
        self.calls = []

    def __call__(self, url, json=None, headers=None, timeout=None, **kwargs):
        path = url.split('ai.test', 1)[1]
        self.calls.append((path, json, headers, timeout))
        planned = self.responses[path]
        if isinstance(planned, list):
            planned = planned.pop(0)
        if isinstance(planned, tuple):
            return http(*planned)
        return http(200, {**planned, 'usage': USAGE})

    def paths(self):
        return [path for path, *_ in self.calls]

    def payload(self, path):
        return next(body for p, body, *_ in self.calls if p == path)

    def fail(self, path, times=2, code='LLM_ERROR'):
        ok = self.responses[path]
        self.responses[path] = [(502, {'error': {'code': code, 'message': '...'}})] * times + [ok]


@override_settings(AI_SERVER_URL='http://ai.test', AI_SERVER_TOKEN='t')
class FinishFixture(LessonFixture):
    def setUp(self):
        super().setUp()
        self.term_ids = {lt.term.name: lt.term_id for lt in self.lesson.lesson_terms.select_related('term')}
        explanation = self.say('word2vec은 단어를 벡터로 바꾸는 방법이야.')
        self.raise_hand(explanation, reason='아직 질문 안 함')
        self.set_term('CBOW', 'explained')
        self.server = FakeAIServer(self.term_ids)
        patcher = patch('common.ai_client.requests.post', side_effect=self.server)
        patcher.start()
        self.addCleanup(patcher.stop)

    def end_lesson(self, client=None):
        return (client or self.client).post(f'{URL}/{self.lesson.id}/end')

    def evaluate(self):
        """수업 종료 직후 상태로 바꾸고 백그라운드 처리를 바로 돌린다."""
        Lesson.objects.filter(pk=self.lesson.pk).update(status='evaluating')
        with self.assertLogs('lessons.finish', level='INFO') as logs:
            run_lesson_finish(self.lesson.id, 'rid-finish')
        self.lesson.refresh_from_db()
        return logs

    def exam(self):
        return Exam.objects.get(lesson=self.lesson, kind='evaluation')


class LessonFinishTests(FinishFixture):
    """백그라운드 처리 run_lesson_finish"""

    def test_whole_flow(self):
        logs = self.evaluate()

        self.assertEqual(self.server.paths(),
                         ['/lessons/note', '/exams/generate', '/exams/solve', '/exams/grade', '/reports/generate'])
        self.assertEqual(self.lesson.status, 'completed')
        self.assertIsNone(self.lesson.error)
        self.assertEqual(Note.objects.get(lesson=self.lesson).content, '# word2vec 정리노트\n\n선생님이 말씀하셨다.')

        exam = self.exam()
        self.assertEqual((exam.status, exam.question_count, exam.correct_count, exam.score), ('completed', 3, 2, 67))
        self.assertIsNotNone(exam.completed_at)
        questions = list(exam.questions.all())
        self.assertEqual([(q.response, q.is_correct) for q in questions],
                         [('0', True), ('1', False), ('단어를 벡터로 나타내요.', True)])
        self.assertEqual([q.term_id for q in questions], [self.term_ids['CBOW'], self.term_ids['원핫 표현'], None])
        self.assertTrue(all(q.answered_at for q in questions))

        report = Report.objects.get(lesson=self.lesson)
        self.assertEqual(report.score, 67)
        self.assertEqual(report.strengths, ['원핫 표현에서 분산 표현으로 자연스럽게 이어 갔어요.'])
        self.assertEqual(report.review_recommendations,
                         [{'term_id': self.term_ids['원핫 표현'], 'text': '원핫 표현의 단점을 다시 보세요.'}])

        self.assertEqual([r.event for r in logs.records], ['job_started', 'job_finished'])

    def test_every_call_uses_background_mode_and_same_request_id(self):
        self.evaluate()
        for path, _, headers, timeout in self.server.calls:
            with self.subTest(path=path):
                self.assertEqual(headers['X-Request-ID'], 'rid-finish')
                self.assertEqual(timeout, 180)

    @override_settings(EVALUATION_QUESTION_COUNT=7, RETEST_QUESTION_COUNT=4)
    def test_evaluation_count_follows_evaluation_setting(self):
        self.evaluate()
        self.assertEqual(self.server.payload('/exams/generate')['count'], 7)

    def test_payloads(self):
        self.evaluate()
        summary = self.lesson.material.summary

        note = self.server.payload('/lessons/note')
        self.assertEqual(note['title'], 'word2vec')
        self.assertEqual(note['persona']['code'], 'minjun')
        self.assertEqual([m['kind'] for m in note['messages']], ['greeting', 'explanation'])

        generate = self.server.payload('/exams/generate')
        self.assertEqual((generate['kind'], generate['count'], generate['summary']), ('evaluation', 5, summary))
        self.assertEqual(generate['question_types'], ['multiple_choice', 'short_answer'])
        self.assertEqual([t['name'] for t in generate['terms']], ['분산 표현', '원핫 표현', 'CBOW'])
        self.assertEqual((generate['focus_term_ids'], generate['exclude_questions']), ([], []))

        solve = self.server.payload('/exams/solve')
        self.assertEqual(set(solve['questions'][0]), {'number', 'question_type', 'content', 'choices'})

        grade = self.server.payload('/exams/grade')
        self.assertEqual([i['number'] for i in grade['items']], [3])
        self.assertEqual(grade['items'][0]['response'], '단어를 벡터로 나타내요.')

        report = self.server.payload('/reports/generate')
        self.assertEqual(report['persona'], {'name': '민준', 'grade_label': '고1'})
        self.assertEqual((report['exam']['correct'], report['exam']['total']), (2, 3))
        self.assertEqual([(t['name'], t['status']) for t in report['terms']][2], ('CBOW', 'explained'))

    def test_student_ai_never_sees_answers_definitions_or_summary(self):
        self.evaluate()
        for path in ['/lessons/note', '/exams/solve']:
            with self.subTest(path=path):
                text = json.dumps(self.server.payload(path), ensure_ascii=False)
                for secret in ['해설1', '의 정의', self.lesson.material.summary, 'correct_answer', 'term_id']:
                    self.assertNotIn(secret, text)

    def test_only_multiple_choice_skips_grading(self):
        questions = self.server.responses['/exams/generate']['questions']
        self.server.responses['/exams/generate'] = {'questions': questions[:2]}
        self.server.responses['/exams/solve'] = {'answers': [{'number': 1, 'response': '0'},
                                                             {'number': 2, 'response': '0'}]}
        self.evaluate()
        self.assertNotIn('/exams/grade', self.server.paths())
        self.assertEqual((self.exam().score, self.lesson.status), (100, 'completed'))

    def test_failure_is_retried_once(self):
        self.server.fail('/exams/solve', times=1)
        with self.assertLogs('common.ai_client', level='WARNING'):
            self.evaluate()
        self.assertEqual(self.server.paths().count('/exams/solve'), 2)
        self.assertEqual(self.lesson.status, 'completed')

    def test_bad_shape_is_retried_once(self):
        good = self.server.responses['/lessons/note']
        self.server.responses['/lessons/note'] = [{'content': '  '}, good]
        with self.assertLogs('common.ai_client', level='WARNING'):
            self.evaluate()
        self.assertEqual(self.lesson.status, 'completed')

    def test_note_failure(self):
        self.server.fail('/lessons/note')
        with self.assertLogs('common.ai_client', level='WARNING'):
            logs = self.evaluate()

        self.assertEqual(self.lesson.status, 'failed')
        self.assertEqual(self.lesson.error,
                         {'code': 'AI_ERROR', 'message': 'AI 처리에 실패했어요.', 'request_id': 'rid-finish'})
        self.assertFalse(Exam.objects.exists())
        failed = logs.records[-1]
        self.assertEqual((failed.event, failed.step, failed.error_code), ('job_failed', 'note', 'LLM_ERROR'))

    def test_exam_failure_marks_exam_too(self):
        self.server.fail('/exams/solve', code='LLM_TIMEOUT')
        with self.assertLogs('common.ai_client', level='WARNING'):
            logs = self.evaluate()

        exam = self.exam()
        self.assertEqual((self.lesson.status, exam.status), ('failed', 'failed'))
        self.assertEqual(exam.error, self.lesson.error)
        self.assertTrue(Note.objects.filter(lesson=self.lesson).exists())
        self.assertFalse(Report.objects.exists())
        self.assertEqual(logs.records[-1].step, 'exam_solve')

    def test_report_failure_keeps_exam_completed(self):
        self.server.fail('/reports/generate')
        with self.assertLogs('common.ai_client', level='WARNING'):
            self.evaluate()
        self.assertEqual((self.lesson.status, self.exam().status), ('failed', 'completed'))
        self.assertIsNone(self.exam().error)

    def test_rerun_skips_finished_steps(self):
        self.server.fail('/reports/generate')
        with self.assertLogs('common.ai_client', level='WARNING'):
            self.evaluate()
        self.server.calls.clear()

        self.evaluate()

        self.assertEqual(self.server.paths(), ['/reports/generate'])
        self.assertEqual(self.lesson.status, 'completed')
        self.assertEqual(Exam.objects.count(), 1)

    def test_rerun_restarts_unfinished_exam(self):
        self.server.fail('/exams/grade')
        with self.assertLogs('common.ai_client', level='WARNING'):
            self.evaluate()
        self.server.calls.clear()

        self.evaluate()

        self.assertEqual(self.server.paths(), ['/exams/generate', '/exams/solve', '/exams/grade', '/reports/generate'])
        self.assertEqual((Exam.objects.count(), ExamQuestion.objects.count()), (1, 3))
        self.assertEqual(self.lesson.status, 'completed')

    def test_skips_lesson_that_is_not_evaluating(self):
        for lesson_status in ['teaching', 'completed', 'failed']:
            with self.subTest(status=lesson_status):
                Lesson.objects.filter(pk=self.lesson.pk).update(status=lesson_status)
                with self.assertLogs('lessons.finish', level='WARNING'):
                    run_lesson_finish(self.lesson.id, 'rid')
        self.assertEqual(self.server.calls, [])

    def test_unexpected_error_marks_failed_and_raises(self):
        Lesson.objects.filter(pk=self.lesson.pk).update(status='evaluating')
        with patch('lessons.finish.Note.objects.create', side_effect=RuntimeError('bug')), \
                self.assertLogs('lessons.finish', level='ERROR'), self.assertRaises(RuntimeError):
            run_lesson_finish(self.lesson.id, 'rid')
        self.lesson.refresh_from_db()
        self.assertEqual((self.lesson.status, self.lesson.error['code']), ('failed', 'AI_ERROR'))


class LessonEndTests(FinishFixture):
    """수업 종료 POST /api/lessons/{lesson_id}/end"""

    def test_end_lesson_enqueues_job(self):
        with self.captureOnCommitCallbacks(execute=True):
            response = self.end_lesson()

        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.json(), {'id': self.lesson.id, 'status': 'evaluating'})
        self.lesson.refresh_from_db()
        self.assertEqual(self.lesson.status, 'evaluating')
        self.assertIsNotNone(self.lesson.ended_at)

        job = DBTaskResult.objects.get()
        self.assertEqual(job.task_path, 'common.jobs.run_job')
        self.assertEqual(job.args_kwargs['args'], [
            'lessons.finish.run_lesson_finish', [self.lesson.id, response.headers['X-Request-ID']],
        ])
        self.assertEqual(self.server.calls, [])  # API 요청 안에서는 AI를 부르지 않음

    def test_job_is_not_enqueued_before_commit(self):
        with self.captureOnCommitCallbacks(execute=False) as callbacks:
            self.end_lesson()
        self.assertEqual(len(callbacks), 1)
        self.assertFalse(DBTaskResult.objects.exists())

    @override_settings(TASKS=IMMEDIATE_TASKS)
    def test_end_to_end_with_immediate_backend(self):
        # 커밋 콜백은 captureOnCommitCallbacks를 나갈 때 돌므로 assertLogs가 바깥에 있어야 함
        with self.assertLogs('lessons.finish', level='INFO'), self.captureOnCommitCallbacks(execute=True):
            self.end_lesson()
        self.lesson.refresh_from_db()
        self.assertEqual(self.lesson.status, 'completed')
        self.assertTrue(Report.objects.filter(lesson=self.lesson).exists())

    def test_raised_hands_are_kept(self):
        self.end_lesson()
        self.assertEqual(HandRaise.objects.get().status, 'raised')

    def test_second_end_is_409(self):
        with self.captureOnCommitCallbacks(execute=True):
            self.end_lesson()
            response = self.end_lesson()
        assert_error(self, response, 409, 'LESSON_NOT_TEACHING')
        self.assertEqual(DBTaskResult.objects.count(), 1)

    def test_access_errors(self):
        assert_error(self, self.client.post(f'{URL}/999999/end'), 404, 'NOT_FOUND')
        assert_error(self, self.end_lesson(client=client_for(make_user(email='o@gmail.com'))), 403, 'FORBIDDEN')
        assert_error(self, self.end_lesson(client=APIClient()), 401, 'UNAUTHORIZED')
        self.lesson.refresh_from_db()
        self.assertEqual(self.lesson.status, 'teaching')


class LessonProgressTests(FinishFixture):
    """진행 상태 GET /api/lessons/{lesson_id}/progress"""

    def progress(self):
        response = self.client.get(f'{URL}/{self.lesson.id}/progress')
        self.assertEqual(response.status_code, 200)
        return response.json()

    def test_teaching(self):
        self.assertEqual(self.progress(), {
            'lesson_status': 'teaching',
            'note': {'status': 'pending', 'note_id': None},
            'exam': {'status': 'pending', 'solved': 0, 'total': 5},
            'report': {'status': 'pending', 'report_id': None},
            'error': None,
        })

    def test_note_running(self):
        Lesson.objects.filter(pk=self.lesson.pk).update(status='evaluating')
        body = self.progress()
        self.assertEqual((body['note']['status'], body['exam']['status'], body['report']['status']),
                         ('running', 'pending', 'pending'))

    def test_exam_solving_with_solved_count(self):
        Lesson.objects.filter(pk=self.lesson.pk).update(status='evaluating')
        note = Note.objects.create(lesson=self.lesson, content='노트')
        exam = Exam.objects.create(lesson=self.lesson, kind='evaluation', status='solving', question_count=3)
        for number, response in [(1, '0'), (2, None), (3, None)]:
            ExamQuestion.objects.create(exam=exam, number=number, question_type='short_answer', content='?',
                                        correct_answer='!', explanation='.', response=response)

        body = self.progress()

        self.assertEqual(body['note'], {'status': 'done', 'note_id': note.id})
        self.assertEqual(body['exam'], {'status': 'solving', 'solved': 1, 'total': 3})
        self.assertEqual(body['report']['status'], 'pending')

    def test_report_running_then_done(self):
        Lesson.objects.filter(pk=self.lesson.pk).update(status='evaluating')
        Note.objects.create(lesson=self.lesson, content='노트')
        Exam.objects.create(lesson=self.lesson, kind='evaluation', status='completed', question_count=3,
                            correct_count=2, score=67)
        self.assertEqual(self.progress()['report']['status'], 'running')

        self.evaluate()  # 남은 보고서 단계만 돈다
        body = self.progress()
        report = Report.objects.get(lesson=self.lesson)
        self.assertEqual(body['lesson_status'], 'completed')
        self.assertEqual(body['report'], {'status': 'done', 'report_id': report.id})

    def test_failed_at_each_step(self):
        cases = [('/lessons/note', ('failed', 'pending', 'pending')),
                 ('/exams/solve', ('done', 'failed', 'pending')),
                 ('/reports/generate', ('done', 'completed', 'failed'))]
        for path, expected in cases:
            with self.subTest(path=path):
                Note.objects.filter(lesson=self.lesson).delete()
                Exam.objects.filter(lesson=self.lesson).delete()
                self.server = FakeAIServer(self.term_ids)
                self.server.fail(path)
                with patch('common.ai_client.requests.post', side_effect=self.server), \
                        self.assertLogs('common.ai_client', level='WARNING'):
                    self.evaluate()
                body = self.progress()
                self.assertEqual(body['lesson_status'], 'failed')
                self.assertEqual((body['note']['status'], body['exam']['status'], body['report']['status']),
                                 expected)
                self.assertEqual(body['error']['code'], 'AI_ERROR')

    def test_access_errors(self):
        assert_error(self, self.client.get(f'{URL}/999999/progress'), 404, 'NOT_FOUND')
        other = client_for(make_user(email='o@gmail.com'))
        assert_error(self, other.get(f'{URL}/{self.lesson.id}/progress'), 403, 'FORBIDDEN')


class LessonNoteTests(FinishFixture):
    """정리노트 GET /api/lessons/{lesson_id}/note"""

    def get(self, client=None):
        return (client or self.client).get(f'{URL}/{self.lesson.id}/note')

    def test_note(self):
        note = Note.objects.create(lesson=self.lesson, content='# 정리노트')
        body = self.get().json()
        self.assertEqual(body, {'id': note.id, 'lesson_id': self.lesson.id, 'persona_name': '민준',
                                'content': '# 정리노트', 'created_at': body['created_at']})
        self.assertTrue(body['created_at'].endswith('+09:00'))

    def test_not_ready_is_409(self):
        assert_error(self, self.get(), 409, 'NOTE_NOT_READY')
        Lesson.objects.filter(pk=self.lesson.pk).update(status='failed')
        assert_error(self, self.get(), 409, 'NOTE_NOT_READY')

    def test_access_errors(self):
        assert_error(self, self.client.get(f'{URL}/999999/note'), 404, 'NOT_FOUND')
        assert_error(self, self.get(client=client_for(make_user(email='o@gmail.com'))), 403, 'FORBIDDEN')
        assert_error(self, self.get(client=APIClient()), 401, 'UNAUTHORIZED')
