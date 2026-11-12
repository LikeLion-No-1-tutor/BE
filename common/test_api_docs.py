"""API 문서 (Swagger).

- 운영(API_DOCS=False)에서는 문서 경로가 없다.
- 모든 API가 경고 없이 문서에 있다.
- 실제 응답이 문서의 모양과 같다. 문서에 없는 필드가 있거나, 문서의 필드가 빠지거나, 타입이 다르면 실패한다.
"""
import importlib
import re
import tempfile
from io import StringIO
from unittest.mock import patch

import jsonschema
from django.conf import settings
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.urls import URLPattern, URLResolver, clear_url_caches, get_resolver
from django.utils import timezone
from drf_spectacular.generators import SchemaGenerator
from rest_framework.test import APIClient

from common.docs_examples import COMPONENTS
from common.testing import client_for, make_ready_material, make_user
from exams.models import Exam, ExamQuestion, Report
from exams.test_reports import add_exam, make_lesson
from lessons.models import Lesson, LessonTerm, Note
from materials.models import Material
from materials.tests import FakeResponse
from personas.models import Persona

DOCS_PATHS = {'/api/docs', '/api/schema'}
HTTP_METHODS = ['get', 'post', 'put', 'patch', 'delete']


def reload_urls():
    clear_url_caches()
    importlib.reload(importlib.import_module(settings.ROOT_URLCONF))


class DocsRouteTests(TestCase):
    def open_urls(self, api_docs):
        override = override_settings(API_DOCS=api_docs)
        override.enable()
        self.addCleanup(reload_urls)
        self.addCleanup(override.disable)
        reload_urls()

    def test_closed_when_api_docs_is_off(self):
        self.open_urls(False)
        for path in DOCS_PATHS:
            response = self.client.get(path)
            self.assertEqual(response.status_code, 404, path)

    def test_open_without_login_when_api_docs_is_on(self):
        self.open_urls(True)
        docs = self.client.get('/api/docs')
        self.assertEqual(docs.status_code, 200)
        self.assertContains(docs, 'swagger-ui')
        schema = self.client.get('/api/schema', HTTP_ACCEPT='application/vnd.oai.openapi+json')
        self.assertEqual(schema.status_code, 200)
        self.assertEqual(schema.json()['info']['title'], '티칭로그 API')


def api_operations():
    """URL에 연결된 API의 (경로, 메서드). 경로는 문서 모양 /api/lessons/{lesson_id}"""
    found = set()

    def walk(patterns, prefix=''):
        for pattern in patterns:
            if isinstance(pattern, URLResolver):
                walk(pattern.url_patterns, prefix + str(pattern.pattern))
            elif isinstance(pattern, URLPattern):
                path = '/' + re.sub(r'<(?:\w+:)?(\w+)>', r'{\1}', prefix + str(pattern.pattern))
                view = getattr(pattern.callback, 'view_class', None)
                if path.startswith('/api/') and path not in DOCS_PATHS and view is not None:
                    found.update((path, method) for method in HTTP_METHODS if hasattr(view, method))

    walk(get_resolver().url_patterns)
    return found


def build_schema():
    return SchemaGenerator().get_schema(request=None, public=True)


class SchemaTests(TestCase):
    def test_every_api_is_documented(self):
        schema = build_schema()
        documented = {(path, method) for path, item in schema['paths'].items() for method in item}
        self.assertEqual(documented, api_operations())
        self.assertEqual(len(documented), 24)

    def test_generates_without_warnings(self):
        out = tempfile.NamedTemporaryFile(suffix='.yml')
        self.addCleanup(out.close)
        # 경고가 하나라도 있으면 실패
        call_command('spectacular', '--validate', '--fail-on-warn', '--file', out.name, stderr=StringIO())

    def test_every_operation_has_summary_tag_and_documented_errors(self):
        for path, item in build_schema()['paths'].items():
            for method, operation in item.items():
                with self.subTest(path=path, method=method):
                    self.assertTrue(operation.get('summary'))
                    self.assertEqual(len(operation['tags']), 1)
                    self.assertTrue(any(code.startswith('2') for code in operation['responses']))
                    self.assertTrue(any(code.startswith('4') for code in operation['responses']))

    def test_logged_in_apis_require_bearer_token(self):
        public = {'/api/auth/google', '/api/auth/refresh'}
        for path, item in build_schema()['paths'].items():
            for method, operation in item.items():
                with self.subTest(path=path, method=method):
                    security = operation.get('security')
                    if path in public:
                        self.assertEqual(security, [{}])
                    else:
                        self.assertEqual(security, [{'jwtAuth': []}])

    def test_developer_notes_are_not_in_docs(self):
        """뷰와 serializer의 docstring(명세 번호 등 개발자용 메모)은 문서에 나오지 않는다."""
        schema = build_schema()
        self.assertFalse(any('description' in c for c in schema['components']['schemas'].values()))
        for item in schema['paths'].values():
            for operation in item.values():
                self.assertNotRegex(operation.get('description', ''), r'\d{2}\. ')


class ExampleTests(TestCase):
    """Swagger에 "string", 0 대신 실제로 쓸 만한 값이 보이는지"""

    def setUp(self):
        self.schema = build_schema()
        self.components = self.schema['components']['schemas']

    def test_every_field_has_an_example_that_fits(self):
        for name, component in self.components.items():
            for field, prop in component.get('properties', {}).items():
                if '$ref' in prop or 'allOf' in prop or prop.get('format') == 'binary':
                    continue  # 다른 모양(그 모양의 필드에 예시가 있음)이나 파일
                if prop.get('type') == 'array' and '$ref' in prop['items']:
                    continue
                with self.subTest(component=name, field=field):
                    self.assertIn('example', prop)
                    jsonschema.validate(prop['example'], to_json_schema(prop, self.components))

    def test_example_names_exist(self):
        """예시 파일에 문서에 없는 모양이나 필드 이름이 남아 있지 않다 (이름을 바꾸고 예시를 빠뜨린 경우)."""
        for name, fields in COMPONENTS.items():
            with self.subTest(component=name):
                self.assertIn(name, self.components)
                self.assertLessEqual(set(fields), set(self.components[name]['properties']))

    def test_every_error_code_has_an_example(self):
        for path, item in self.schema['paths'].items():
            for method, operation in item.items():
                for status_code, response in operation['responses'].items():
                    if status_code.startswith('2'):
                        continue
                    with self.subTest(path=path, method=method, status=status_code):
                        content = response['content']['application/json']
                        codes = re.findall(r'`([A-Z_]+)`', response['description'])
                        examples = list(content['examples'].values())
                        self.assertEqual([e['value']['error']['code'] for e in examples], codes)
                        self.assertEqual([e['summary'] for e in examples], codes)
                        schema = to_json_schema(content['schema'], self.components)
                        for example in examples:
                            jsonschema.validate(example['value'], schema)


def to_json_schema(node, components):
    """OpenAPI 3.0 스키마 → JSON Schema. $ref를 풀고, nullable을 null 허용으로 바꾸고,
    문서에 없는 필드가 오면 실패하도록 additionalProperties를 막는다."""
    if isinstance(node, list):
        return [to_json_schema(item, components) for item in node]
    if not isinstance(node, dict):
        return node
    if '$ref' in node:
        return to_json_schema(components[node['$ref'].rsplit('/', 1)[-1]], components)
    node = {key: to_json_schema(value, components) for key, value in node.items()}
    if node.get('type') == 'object' and 'properties' in node:
        node.setdefault('additionalProperties', False)
    if node.pop('nullable', False):
        return {'anyOf': [node, {'type': 'null'}]}
    return node


@override_settings(AI_SERVER_URL='http://ai.test', AI_SERVER_TOKEN='t')
class ResponsesMatchDocsTests(TestCase):
    """API를 실제로 불러 응답이 문서와 같은지 확인한다. AI 서버는 경로별로 정해 둔 응답을 돌려준다."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        schema = build_schema()
        cls.components = schema['components']['schemas']
        cls.operations = {
            operation['operationId']: operation for item in schema['paths'].values() for operation in item.values()
        }

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        override = override_settings(TEMP_UPLOAD_DIR=self.tmp.name)
        override.enable()
        self.addCleanup(override.disable)
        self.ai = {}
        patcher = patch(
            'common.ai_client.requests.post',
            lambda url, **kwargs: FakeResponse(200, self.ai[url.replace('http://ai.test', '')]),
        )
        patcher.start()
        self.addCleanup(patcher.stop)
        self.user = make_user()
        self.client = client_for(self.user)
        self.checked = set()

    def test_responses_match_docs(self):
        flows = [
            self.auth_and_me, self.personas, self.materials, self.lesson_flow, self.finished_and_failed_lessons,
            self.reports_and_retests,
        ]
        for flow in flows:
            with self.subTest(flow.__name__):
                flow()
        # 모든 API를 한 번 이상 확인했는지
        self.assertEqual(self.checked, set(self.operations))

    def check(self, response, operation_id, status_code):
        """응답 상태가 status_code이고, 그 상태가 문서에 있고, 본문이 문서 모양과 같은지."""
        self.assertEqual(response.status_code, status_code, response.content[:500])
        operation = self.operations[operation_id]
        documented = operation['responses'].get(str(status_code))
        self.assertIsNotNone(documented, f'{operation_id}: {status_code}가 문서에 없음')
        content = documented.get('content')
        if content is None:
            self.assertEqual(response.content, b'')
        else:
            schema = to_json_schema(content['application/json']['schema'], self.components)
            try:
                jsonschema.validate(response.json(), schema)
            except jsonschema.ValidationError as error:
                self.fail(f'{operation_id} {status_code}: {error.message} at {list(error.absolute_path)}')
        self.checked.add(operation_id)
        return response.json() if content is not None else None

    # 로그인과 내 정보 ----------------------------------------------------

    def auth_and_me(self):
        client = APIClient()
        google = {'sub': 'sub-new', 'email': 'new@gmail.com', 'email_verified': True}
        with patch('google.oauth2.id_token.verify_oauth2_token', return_value=google):
            body = self.check(client.post('/api/auth/google', {'id_token': 'x'}, format='json'), 'google_login', 200)
        self.check(client.post('/api/auth/google', {}, format='json'), 'google_login', 400)
        body = self.check(
            client.post('/api/auth/refresh', {'refresh_token': body['refresh_token']}, format='json'),
            'token_refresh', 200,
        )
        self.check(client.post('/api/auth/refresh', {'refresh_token': 'bad'}, format='json'), 'token_refresh', 401)

        client.credentials(HTTP_AUTHORIZATION=f"Bearer {body['access_token']}")
        self.check(client.get('/api/users/me'), 'me', 200)
        self.check(client.patch('/api/users/me', {'nickname': '새선생'}, format='json'), 'me_update', 200)
        self.check(client.patch('/api/users/me', {}, format='json'), 'me_update', 400)
        self.check(
            client.post('/api/auth/logout', {'refresh_token': body['refresh_token']}, format='json'), 'logout', 204,
        )
        self.check(client.delete('/api/users/me'), 'me_delete', 204)
        self.check(APIClient().get('/api/users/me'), 'me', 401)

    def personas(self):
        self.check(self.client.get('/api/personas'), 'persona_list', 200)
        self.check(client_for(make_user('no-nick@gmail.com', nickname=None)).get('/api/personas'), 'persona_list', 409)

    # 자료 ---------------------------------------------------------------

    def materials(self):
        body = self.check(
            self.client.post('/api/materials', {'title': 'word2vec', 'text': '본문'}, format='multipart'),
            'material_upload', 202,
        )
        self.check(self.client.get(f"/api/materials/{body['id']}"), 'material_status', 200)
        self.check(
            self.client.post('/api/materials', {'title': 'x', 'file': SimpleUploadedFile('a.exe', b'data')}, format='multipart'),
            'material_upload', 400,
        )
        ready = make_ready_material(self.user)
        self.check(self.client.get(f'/api/materials/{ready.id}'), 'material_status', 200)
        failed = Material.objects.create(
            user=self.user, title='실패', source_type='text', status='failed',
            error={'code': 'UNREADABLE_MATERIAL', 'message': '자료에서 내용을 읽을 수 없어요.', 'request_id': 'r'},
        )
        self.check(self.client.get(f'/api/materials/{failed.id}'), 'material_status', 200)
        other = make_ready_material(make_user('material-other@gmail.com'))
        self.check(self.client.get(f'/api/materials/{other.id}'), 'material_status', 403)
        self.check(self.client.get('/api/materials/999999'), 'material_status', 404)

    # 수업 ---------------------------------------------------------------

    def lesson_flow(self):
        material = make_ready_material(self.user, terms=['분산 표현', 'CBOW'])
        persona = Persona.objects.get(code='minjun')
        start = {'material_id': material.id, 'persona_id': persona.id}
        lesson = self.check(self.client.post('/api/lessons', start, format='json'), 'lesson_start', 201)
        self.check(self.client.post('/api/lessons', start, format='json'), 'lesson_start', 409)
        url = f"/api/lessons/{lesson['id']}"
        term_id = lesson['terms'][0]['term_id']

        self.check(self.client.get(url), 'lesson_detail', 200)
        self.check(self.client.get(f'{url}/messages'), 'lesson_messages', 200)

        # 설명 → 손 듦
        self.ai['/lessons/messages/analyze'] = {
            'term_updates': [{'term_id': term_id, 'status': 'explained'}], 'hand_raise': {'reason': '메모'}, 'usage': [],
        }
        sent = self.check(
            self.client.post(f'{url}/messages', {'content': '분산 표현은 벡터예요.'}, format='json'), 'message_send', 201,
        )
        self.assertIsNotNone(sent['new_hand_raise'])
        # 질문 받기
        self.ai['/lessons/questions'] = {'content': '왜 벡터인가요?', 'usage': []}
        hand_raise_url = f"{url}/hand-raises/{sent['new_hand_raise']['id']}/ask"
        asked = self.check(self.client.post(hand_raise_url), 'hand_raise_ask', 201)
        self.check(self.client.post(hand_raise_url), 'hand_raise_ask', 409)
        # 답변 → 손 들지 않음
        self.ai['/lessons/messages/analyze'] = {'term_updates': [], 'hand_raise': None, 'usage': []}
        sent = self.check(
            self.client.post(
                f'{url}/messages', {'content': '의미를 담으려고요.', 'reply_to_id': asked['question']['id']}, format='json',
            ),
            'message_send', 201,
        )
        self.assertIsNone(sent['new_hand_raise'])
        self.check(self.client.post(f'{url}/messages', {'content': ''}, format='json'), 'message_send', 400)
        self.ai['/lessons/messages/analyze'] = {'unexpected': True}
        self.check(self.client.post(f'{url}/messages', {'content': '설명'}, format='json'), 'message_send', 502)

        self.check(self.client.get(f'{url}/messages', {'limit': 2}), 'lesson_messages', 200)
        self.check(self.client.get(url), 'lesson_detail', 200)

        # 종료 → 진행 중
        self.check(self.client.post(f'{url}/end'), 'lesson_end', 202)
        self.check(self.client.post(f'{url}/end'), 'lesson_end', 409)
        self.check(self.client.get(f'{url}/progress'), 'lesson_progress', 200)
        self.check(self.client.get(f'{url}/note'), 'lesson_note', 409)
        self.check(self.client.get('/api/lessons'), 'lesson_list', 200)
        self.check(self.client.get('/api/lessons', {'status': 'x'}), 'lesson_list', 400)
        self.check(client_for(make_user('lesson-other@gmail.com')).get(url), 'lesson_detail', 403)
        self.check(self.client.get('/api/lessons/999999'), 'lesson_detail', 404)

    def finished_and_failed_lessons(self):
        lesson = self.completed_lesson()
        url = f'/api/lessons/{lesson.id}'
        self.check(self.client.get(url), 'lesson_detail', 200)
        self.check(self.client.get(f'{url}/progress'), 'lesson_progress', 200)
        self.check(self.client.get(f'{url}/note'), 'lesson_note', 200)
        self.check(self.client.get('/api/lessons', {'status': 'completed', 'size': 1}), 'lesson_list', 200)

        failed = make_lesson(self.user, '실패한 수업', day=2, status='failed')
        Lesson.objects.filter(pk=failed.pk).update(
            ended_at=timezone.now(), error={'code': 'AI_ERROR', 'message': 'AI 처리에 실패했어요.', 'request_id': 'r'},
        )
        self.check(self.client.get(f'/api/lessons/{failed.id}/progress'), 'lesson_progress', 200)

    def completed_lesson(self):
        lesson = make_lesson(self.user, 'word2vec', day=1)
        Lesson.objects.filter(pk=lesson.pk).update(ended_at=lesson.started_at)
        LessonTerm.objects.filter(lesson=lesson, term__name='분산 표현').update(status='explained')
        cbow = lesson.material.terms.get(name='CBOW')
        Note.objects.create(lesson=lesson, content='# 정리노트', sections=[
            {'term_id': cbow.id, 'name': 'CBOW', 'concept': '주변 단어로 가운데 단어를 맞힘', 'questions': [
                {'status': 'answered', 'question': '왜요?', 'answer': '문맥을 배우려고.'},
                {'status': 'unseen', 'question': '창 크기는요?', 'answer': None},
            ]},
            {'term_id': None, 'name': '그 밖에 배운 내용', 'concept': '', 'questions': []},
        ])
        add_exam(lesson, 'evaluation', 50, minutes=30, results=[(True, '분산 표현'), (False, 'CBOW'), (None, None)])
        cbow = lesson.material.terms.get(name='CBOW')
        Report.objects.create(
            lesson=lesson, score=50, strengths=['예시가 좋았어요'],
            review_recommendations=[{'term_id': cbow.id, 'text': 'CBOW를 다시 설명해 보세요'}],
        )
        return lesson

    # 성장보고서와 재시험 -------------------------------------------------

    def reports_and_retests(self):
        lesson = self.completed_lesson()
        report = lesson.report
        self.check(self.client.get('/api/reports'), 'report_list', 200)
        self.check(self.client.get('/api/reports', {'page': 0}), 'report_list', 400)
        self.check(self.client.get(f'/api/reports/{report.id}'), 'report_detail', 200)

        start_url = f'/api/reports/{report.id}/retests'
        retest = self.check(self.client.post(start_url, {}, format='json'), 'retest_start', 202)
        self.check(self.client.post(start_url, {}, format='json'), 'retest_start', 409)
        self.check(self.client.post(start_url, {'focus': 'x'}, format='json'), 'retest_start', 400)
        self.check(self.client.get(f"/api/retests/{retest['id']}"), 'retest_detail', 200)

        # 출제가 끝난 재시험
        exam = Exam.objects.get(pk=retest['id'])
        cbow = lesson.material.terms.get(name='CBOW')
        ExamQuestion.objects.create(
            exam=exam, number=1, question_type='multiple_choice', content='Q1', choices=['a', 'b'],
            correct_answer='0', explanation='해설1', term=cbow,
        )
        ExamQuestion.objects.create(
            exam=exam, number=2, question_type='short_answer', content='Q2', correct_answer='답', explanation='해설2',
        )
        Exam.objects.filter(pk=exam.pk).update(status='solving', question_count=2)
        url = f'/api/retests/{exam.id}'
        self.check(self.client.get(url), 'retest_detail', 200)
        self.check(self.client.post(f'{url}/questions/1/answer', {'response': '0'}, format='json'), 'retest_answer', 200)
        self.check(self.client.post(f'{url}/questions/1/answer', {'response': '0'}, format='json'), 'retest_answer', 409)
        self.check(self.client.post(f'{url}/questions/2/answer', {'response': ''}, format='json'), 'retest_answer', 400)
        self.ai['/exams/grade'] = {'results': [{'number': 2, 'is_correct': False, 'reason': '.'}], 'usage': []}
        self.check(self.client.post(f'{url}/questions/2/answer', {'response': '모름'}, format='json'),
                   'retest_answer', 200)
        self.check(self.client.get(url), 'retest_detail', 200)
        self.check(self.client.post(f'{url}/complete'), 'retest_complete', 200)
        self.check(self.client.post(f'{url}/complete'), 'retest_complete', 409)

        detail = self.check(self.client.get(f'/api/reports/{report.id}'), 'report_detail', 200)
        self.assertIsNotNone(detail['comparison'])
        self.check(self.client.get('/api/reports'), 'report_list', 200)

        failed = Exam.objects.create(
            lesson=lesson, kind='retest', status='failed', question_count=2,
            error={'code': 'AI_ERROR', 'message': 'AI 처리에 실패했어요.', 'request_id': 'r'},
        )
        self.check(self.client.get(f'/api/retests/{failed.id}'), 'retest_detail', 200)
        self.check(self.client.get('/api/retests/999999'), 'retest_detail', 404)
