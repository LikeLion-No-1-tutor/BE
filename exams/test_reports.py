"""학습 목록, 성장보고서 목록, 성장보고서 상세"""
from datetime import timedelta

from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from rest_framework.test import APIClient

from common.testing import client_for, make_ready_material, make_user
from lessons.models import Lesson, LessonTerm
from personas.models import Persona

from .models import Exam, ExamQuestion, Report

BASE = timezone.now() - timedelta(days=30)


def assert_error(test, response, http_status, code):
    test.assertEqual(response.status_code, http_status, response.content)
    test.assertEqual(response.json()['error']['code'], code)


def make_lesson(user, title, day, status='completed', terms=('분산 표현', '원핫 표현', 'CBOW')):
    """day일째에 시작한 수업. 용어 체크는 모두 todo."""
    material = make_ready_material(user, title=title, terms=terms)
    lesson = Lesson.objects.create(user=user, material=material, persona=Persona.objects.get(code='minjun'),
                                   status=status, started_at=BASE + timedelta(days=day))
    LessonTerm.objects.bulk_create(LessonTerm(lesson=lesson, term=term) for term in material.terms.all())
    return lesson


def add_exam(lesson, kind, score, minutes, status='completed', results=()):
    """수업 시작 minutes분 뒤에 끝난 시험. results: [(is_correct, 용어 이름 또는 None)]"""
    completed_at = lesson.started_at + timedelta(minutes=minutes) if status == 'completed' else None
    total = len(results) or 10
    exam = Exam.objects.create(
        lesson=lesson, kind=kind, status=status, question_count=total,
        correct_count=sum(1 for ok, _ in results if ok) if results else None,
        score=score if status == 'completed' else None, completed_at=completed_at,
    )
    terms = {t.name: t for t in lesson.material.terms.all()}
    for number, (is_correct, term_name) in enumerate(results, start=1):
        ExamQuestion.objects.create(
            exam=exam, number=number, question_type='multiple_choice', content=f'Q{number}', choices=['a', 'b'],
            correct_answer='0', explanation='.', term=terms.get(term_name), response='0' if is_correct else '1',
            is_correct=is_correct,
        )
    return exam


def add_report(lesson, score, minutes=40):
    report = Report.objects.create(lesson=lesson, score=score, strengths=['잘했어요'],
                                   review_recommendations=[{'term_id': None, 'text': '복습'}])
    Report.objects.filter(pk=report.pk).update(created_at=lesson.started_at + timedelta(minutes=minutes))
    report.refresh_from_db()
    return report


class LessonListTests(TestCase):
    """학습 목록 GET /api/lessons"""

    def setUp(self):
        self.user = make_user()
        self.client = client_for(self.user)
        self.old = make_lesson(self.user, 'RNN', day=1)
        add_exam(self.old, 'evaluation', 80, minutes=30)
        self.old_report = add_report(self.old, 80)
        self.done = make_lesson(self.user, 'word2vec', day=2)
        add_exam(self.done, 'evaluation', 60, minutes=30)
        add_exam(self.done, 'retest', 67, minutes=60)
        add_exam(self.done, 'retest', None, minutes=90, status='generating')  # 끝나지 않은 재시험은 빼고 계산
        self.report = add_report(self.done, 60)
        self.teaching = make_lesson(self.user, 'LSTM', day=3, status='teaching')

    def get(self, query=''):
        response = self.client.get(f'/api/lessons{query}')
        self.assertEqual(response.status_code, 200, response.content)
        return response.json()

    def test_list_newest_first(self):
        body = self.get()

        self.assertEqual([item['id'] for item in body['items']], [self.teaching.id, self.done.id, self.old.id])
        self.assertEqual((body['page'], body['size'], body['total']), (1, 20, 3))
        self.assertEqual(body['items'][1], {
            'id': self.done.id, 'title': 'word2vec', 'persona_name': '민준', 'status': 'completed',
            'started_at': body['items'][1]['started_at'], 'score': 60, 'latest_score': 67,
            'report_id': self.report.id,
        })
        self.assertTrue(body['items'][1]['started_at'].endswith('+09:00'))
        self.assertEqual({k: body['items'][0][k] for k in ['status', 'score', 'latest_score', 'report_id']},
                         {'status': 'teaching', 'score': None, 'latest_score': None, 'report_id': None})
        self.assertEqual((body['items'][2]['score'], body['items'][2]['latest_score']), (80, 80))

    def test_latest_score_follows_completed_at(self):
        # 나중에 만들었지만 먼저 끝난 시험
        add_exam(self.done, 'retest', 90, minutes=45)
        self.assertEqual(self.get()['items'][1]['latest_score'], 67)

    def test_status_filter(self):
        self.assertEqual([i['id'] for i in self.get('?status=teaching')['items']], [self.teaching.id])
        self.assertEqual([i['id'] for i in self.get('?status=completed')['items']], [self.done.id, self.old.id])

    def test_invalid_status_is_400(self):
        for status in ['evaluating', 'failed', 'abc']:
            with self.subTest(status=status):
                response = self.client.get(f'/api/lessons?status={status}')
                assert_error(self, response, 400, 'VALIDATION_ERROR')

    def test_empty_status_means_all(self):
        self.assertEqual(self.get('?status=')['total'], 3)

    def test_pagination(self):
        body = self.get('?page=2&size=2')
        self.assertEqual([i['id'] for i in body['items']], [self.old.id])
        self.assertEqual(body['total'], 3)
        assert_error(self, self.client.get('/api/lessons?page=0'), 400, 'VALIDATION_ERROR')

    def test_only_my_lessons(self):
        other = make_user(email='o@gmail.com')
        make_lesson(other, '남의 수업', day=5)
        self.assertEqual(self.get()['total'], 3)
        self.assertEqual(client_for(other).get('/api/lessons').json()['total'], 1)

    def test_query_count_does_not_grow_with_lessons(self):
        def count_queries():
            with CaptureQueriesContext(connection) as queries:
                self.get()
            return len(queries)

        before = count_queries()
        for day in range(10, 15):
            lesson = make_lesson(self.user, f'수업 {day}', day=day)
            add_exam(lesson, 'evaluation', 50, minutes=30)
            add_report(lesson, 50)
        self.assertEqual(count_queries(), before)

    def test_errors(self):
        assert_error(self, APIClient().get('/api/lessons'), 401, 'UNAUTHORIZED')
        assert_error(self, client_for(make_user(email='n@gmail.com', nickname=None)).get('/api/lessons'),
                     409, 'NICKNAME_REQUIRED')


class ReportListTests(TestCase):
    """성장보고서 목록 GET /api/reports"""

    def setUp(self):
        self.user = make_user()
        self.client = client_for(self.user)
        self.old = make_lesson(self.user, '단어의 분산 표현', day=1)
        add_exam(self.old, 'evaluation', 80, minutes=30)
        self.old_report = add_report(self.old, 80)
        self.new = make_lesson(self.user, 'word2vec', day=2)
        add_exam(self.new, 'evaluation', 60, minutes=30)
        add_exam(self.new, 'retest', 67, minutes=60)
        add_exam(self.new, 'retest', None, minutes=90, status='failed')
        self.new_report = add_report(self.new, 60)
        make_lesson(self.user, '보고서 없는 수업', day=3, status='evaluating')

    def test_list_newest_first(self):
        body = self.client.get('/api/reports').json()

        self.assertEqual([item['id'] for item in body['items']], [self.new_report.id, self.old_report.id])
        self.assertEqual(body['total'], 2)
        self.assertEqual(body['items'][0], {
            'id': self.new_report.id, 'lesson_id': self.new.id, 'title': 'word2vec', 'score': 60,
            'latest_score': 67, 'retest_count': 1, 'created_at': body['items'][0]['created_at'],
        })
        self.assertEqual((body['items'][1]['latest_score'], body['items'][1]['retest_count']), (80, 0))

    def test_size_one_for_main_card(self):
        body = self.client.get('/api/reports?size=1').json()
        self.assertEqual([item['id'] for item in body['items']], [self.new_report.id])
        self.assertEqual((body['size'], body['total']), (1, 2))

    def test_only_my_reports(self):
        other = make_user(email='o@gmail.com')
        lesson = make_lesson(other, '남의 수업', day=4)
        add_report(lesson, 10)
        self.assertEqual(self.client.get('/api/reports').json()['total'], 2)

    def test_errors(self):
        assert_error(self, APIClient().get('/api/reports'), 401, 'UNAUTHORIZED')
        assert_error(self, client_for(make_user(email='n@gmail.com', nickname=None)).get('/api/reports'),
                     409, 'NICKNAME_REQUIRED')


class ReportDetailTests(TestCase):
    """성장보고서 상세 GET /api/reports/{report_id}"""

    def setUp(self):
        self.user = make_user()
        self.client = client_for(self.user)
        self.lesson = make_lesson(self.user, 'word2vec', day=1, terms=['분산 표현', '원핫 표현', 'CBOW', '스킵그램'])
        LessonTerm.objects.filter(lesson=self.lesson, term__name='분산 표현').update(status='explained')
        LessonTerm.objects.filter(lesson=self.lesson, term__name='스킵그램').update(status='mentioned')
        self.evaluation = add_exam(self.lesson, 'evaluation', 40, minutes=30, results=[
            (True, '분산 표현'), (False, 'CBOW'), (False, 'CBOW'), (False, '스킵그램'), (True, None),
        ])
        self.report = add_report(self.lesson, 40)
        self.term_ids = {t.name: t.id for t in self.lesson.material.terms.all()}

    def get(self, report_id=None, client=None):
        return (client or self.client).get(f'/api/reports/{report_id or self.report.id}')

    def test_without_retest(self):
        response = self.get()

        self.assertEqual(response.status_code, 200, response.content)
        body = response.json()
        self.assertEqual(body['id'], self.report.id)
        self.assertEqual(body['lesson'], {
            'id': self.lesson.id, 'title': 'word2vec', 'persona_name': '민준', 'persona_grade_label': '고1',
            'started_at': body['lesson']['started_at'],
        })
        self.assertEqual(body['score'], 40)
        self.assertEqual(body['score_history'], [{
            'exam_id': self.evaluation.id, 'kind': 'evaluation', 'score': 40,
            'completed_at': body['score_history'][0]['completed_at'],
        }])
        self.assertIsNone(body['comparison'])
        self.assertEqual((body['exam']['correct'], body['exam']['total']), (2, 5))
        self.assertEqual(body['exam']['results'], [
            {'number': 1, 'is_correct': True, 'term_id': self.term_ids['분산 표현']},
            {'number': 2, 'is_correct': False, 'term_id': self.term_ids['CBOW']},
            {'number': 3, 'is_correct': False, 'term_id': self.term_ids['CBOW']},
            {'number': 4, 'is_correct': False, 'term_id': self.term_ids['스킵그램']},
            {'number': 5, 'is_correct': True, 'term_id': None},
        ])
        self.assertEqual(body['terms'], {'explained': 1, 'total': 4})
        self.assertEqual(body['strengths'], ['잘했어요'])
        self.assertEqual(body['missed_terms'], [
            {'term_id': self.term_ids['원핫 표현'], 'name': '원핫 표현', 'status': 'todo', 'wrong_count': 0},
            {'term_id': self.term_ids['CBOW'], 'name': 'CBOW', 'status': 'todo', 'wrong_count': 2},
            {'term_id': self.term_ids['스킵그램'], 'name': '스킵그램', 'status': 'mentioned', 'wrong_count': 1},
        ])
        self.assertEqual(body['review_recommendations'], [{'term_id': None, 'text': '복습'}])
        for field in ['created_at', 'updated_at']:
            self.assertTrue(body[field].endswith('+09:00'))

    def test_with_retests(self):
        first = add_exam(self.lesson, 'retest', 60, minutes=60, results=[(False, 'CBOW')])
        second = add_exam(self.lesson, 'retest', 80, minutes=90)
        add_exam(self.lesson, 'retest', None, minutes=120, status='solving')

        body = self.get().json()

        self.assertEqual([(h['exam_id'], h['kind'], h['score']) for h in body['score_history']],
                         [(self.evaluation.id, 'evaluation', 40), (first.id, 'retest', 60), (second.id, 'retest', 80)])
        self.assertEqual(body['comparison'], {'current_score': 80, 'previous_score': 60, 'diff': 20})
        self.assertEqual(body['score'], 40)  # 보고서의 점수는 학생 AI 평가 점수 그대로
        # 놓친 개념의 오답 수는 평가 시험만 센다 (재시험 오답은 넣지 않음)
        cbow = next(t for t in body['missed_terms'] if t['name'] == 'CBOW')
        self.assertEqual(cbow['wrong_count'], 2)

    def test_score_went_down(self):
        add_exam(self.lesson, 'retest', 20, minutes=60)
        self.assertEqual(self.get().json()['comparison'], {'current_score': 20, 'previous_score': 40, 'diff': -20})

    def test_errors(self):
        assert_error(self, self.get(report_id=999999), 404, 'NOT_FOUND')
        self.assertEqual(self.get(report_id=999999).json()['error']['message'], '성장보고서를 찾을 수 없어요.')
        assert_error(self, self.get(client=client_for(make_user(email='o@gmail.com'))), 403, 'FORBIDDEN')
        assert_error(self, self.get(client=APIClient()), 401, 'UNAUTHORIZED')
