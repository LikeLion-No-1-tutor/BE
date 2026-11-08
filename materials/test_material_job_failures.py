"""자료 정리 작업(material_process)의 실패 처리.

AI 서버가 약속과 다른 응답을 주거나, 작업 중 예상하지 못한 예외가 나도
원본은 반드시 지워지고 자료는 failed로 끝나야 합니다 (processing에 멈추면 안 됨).
"""
import shutil
import tempfile
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import override_settings
from django.urls import reverse
from rest_framework.test import APITestCase

from materials import storage
from materials import tasks as material_tasks
from materials.models import Material
from materials.tests import IMMEDIATE_TASKS, USAGE, FakeAiServer, FakeResponse, ok_summary, ok_terms

User = get_user_model()


class NotJsonResponse(FakeResponse):
    """본문이 JSON이 아닌 응답 (예: 프록시의 HTML 에러 페이지)"""

    def __init__(self, status_code):
        super().__init__(status_code, None)

    def json(self):
        raise ValueError('not json')


@override_settings(AI_SERVER_URL='http://ai.test', AI_SERVER_TOKEN='internal-token', TASKS=IMMEDIATE_TASKS)
class MaterialJobFailureTests(APITestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.override = override_settings(TEMP_UPLOAD_DIR=self.tmp)
        self.override.enable()
        self.user = User.objects.create_user(email='jimin@gmail.com', google_sub='sub-jimin', nickname='지민')
        self.client.force_authenticate(self.user)

    def tearDown(self):
        self.override.disable()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def upload(self, ai):
        """텍스트 자료를 올리고 커밋 뒤 백그라운드 작업까지 실행. (자료, 응답의 요청 ID)"""
        with patch('common.ai_client.requests.post', side_effect=ai), \
                self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(
                reverse('material-create'), {'title': 'word2vec', 'text': 'word2vec은 ...'}, format='multipart',
            )
        self.assertEqual(response.status_code, 202, response.content)
        return Material.objects.get(pk=response.json()['id']), response.headers['X-Request-ID']

    def assert_failed_and_cleaned(self, material, request_id):
        material.refresh_from_db()
        self.assertEqual(material.status, Material.Status.FAILED)
        self.assertEqual(material.error, {'code': 'AI_ERROR', 'message': 'AI 처리에 실패했어요.', 'request_id': request_id})
        self.assertIsNotNone(material.original_deleted_at)
        self.assertFalse(storage.material_dir(material.id).exists())

    # AI 서버가 약속과 다른 응답 --------------------------------------------

    def test_200_with_non_object_bodies(self):
        for body in [[], None, 'ok', 3]:
            with self.subTest(body=body):
                ai = FakeAiServer(terms=[FakeResponse(200, body), FakeResponse(200, body)])
                with self.assertLogs('common.ai_client', level='WARNING') as logs:
                    material, request_id = self.upload(ai)
                self.assert_failed_and_cleaned(material, request_id)
                self.assertEqual(ai.paths(), ['/materials/terms', '/materials/terms'])  # 한 번 다시 부름
                self.assertIn('INVALID_RESPONSE', logs.output[0])

    def test_200_not_json(self):
        ai = FakeAiServer(terms=[NotJsonResponse(200), NotJsonResponse(200)])
        with self.assertLogs('common.ai_client', level='WARNING'):
            material, request_id = self.upload(ai)
        self.assert_failed_and_cleaned(material, request_id)

    def test_error_responses_with_unexpected_shape(self):
        for response in [FakeResponse(500, {'error': 'boom'}), FakeResponse(502, ['x']),
                         FakeResponse(503, {'error': {'code': 7}}), NotJsonResponse(504)]:
            with self.subTest(status=response.status_code):
                ai = FakeAiServer(terms=[response, response])
                with self.assertLogs('common.ai_client', level='WARNING') as logs:
                    material, request_id = self.upload(ai)
                self.assert_failed_and_cleaned(material, request_id)
                self.assertIn(f'HTTP_{response.status_code}', logs.output[0])

    def test_bad_response_then_good_response_succeeds(self):
        ai = FakeAiServer(terms=[FakeResponse(200, []), ok_terms()])
        with self.assertLogs('common.ai_client', level='WARNING'):
            material, _ = self.upload(ai)
        material.refresh_from_db()
        self.assertEqual(material.status, Material.Status.READY)
        self.assertFalse(storage.material_dir(material.id).exists())

    def test_malformed_usage_does_not_fail_the_job(self):
        ai = FakeAiServer(
            terms=[FakeResponse(200, {'terms': [{'name': 'CBOW', 'definition': '정의'}], 'usage': 'x'})],
            summary=[FakeResponse(200, {'summary': '# 요약', 'usage': [{'input_tokens': '많이'}, 'x', *USAGE]})],
        )
        material, _ = self.upload(ai)
        material.refresh_from_db()
        self.assertEqual(material.status, Material.Status.READY)

    # 작업 중 예상하지 못한 예외 ---------------------------------------------

    def test_unexpected_error_while_saving_terms(self):
        with patch('materials.tasks._save_terms', side_effect=RuntimeError('버그')), \
                self.assertLogs('materials.tasks', level='ERROR') as logs:
            material, request_id = self.upload(FakeAiServer())
        self.assert_failed_and_cleaned(material, request_id)
        crashed = next(r for r in logs.records if r.getMessage() == 'job crashed')
        self.assertEqual((crashed.step, crashed.exception_type), ('terms', 'RuntimeError'))

    def test_unexpected_error_while_reading_original(self):
        with patch('materials.tasks._multipart', side_effect=OSError('읽기 실패')), \
                self.assertLogs('materials.tasks', level='ERROR'):
            material, request_id = self.upload(FakeAiServer())
        self.assert_failed_and_cleaned(material, request_id)

    def test_unexpected_error_after_summary(self):
        ai = FakeAiServer(terms=[ok_terms()], summary=[ok_summary()])
        real_update = material_tasks._update

        def fail_on_summary(material_id, **fields):
            if 'summary' in fields:
                raise RuntimeError('DB 오류')
            return real_update(material_id, **fields)

        with patch('materials.tasks._update', side_effect=fail_on_summary), \
                self.assertLogs('materials.tasks', level='ERROR'):
            material, request_id = self.upload(ai)
        self.assert_failed_and_cleaned(material, request_id)
