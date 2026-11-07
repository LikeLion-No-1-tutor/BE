"""08. 학습 자료 업로드 (+ 백그라운드 material_process) 테스트

AI 서버는 requests.post를 바꿔치기해서 흉내 냅니다.
"""
import json
import shutil
import tempfile
from pathlib import Path
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase
from rest_framework_simplejwt.tokens import RefreshToken

from materials import storage
from materials.models import Material, Term

User = get_user_model()

TERMS = [
    {'name': '분산 표현', 'definition': '단어를 실수 벡터로 나타내는 방법.'},
    {'name': 'CBOW', 'definition': '주변 단어로 가운데 단어를 맞히는 모델.'},
]
SUMMARY = '# word2vec 요약정리\n\n## 핵심 개념\n...'
USAGE = [{'role': 'material', 'model': 'claude-haiku-5-5', 'input_tokens': 10, 'output_tokens': 5}]


class FakeResponse:
    def __init__(self, status_code, body):
        self.status_code = status_code
        self._body = body

    def json(self):
        return self._body


def ok_terms():
    return FakeResponse(200, {'terms': TERMS, 'usage': USAGE})


def ok_summary():
    return FakeResponse(200, {'summary': SUMMARY, 'usage': USAGE})


def ai_error(code='LLM_TIMEOUT', http=504):
    return FakeResponse(http, {'error': {'code': code, 'message': '...', 'request_id': 'x'}})


class FakeAiServer:
    """경로별로 정해 둔 응답을 차례로 돌려주고, 받은 요청을 기록합니다."""

    def __init__(self, terms=None, summary=None):
        self.responses = {
            '/materials/terms': list(terms or [ok_terms()]),
            '/materials/summary': list(summary or [ok_summary()]),
        }
        self.calls = []

    def __call__(self, url, headers=None, json=None, data=None, files=None, timeout=None):
        path = url.replace('http://ai.test', '')
        sent_file = None
        if files:
            name, fh, content_type = files['file']
            sent_file = (name, fh.read(), content_type)
        self.calls.append({'path': path, 'headers': headers, 'data': data, 'file': sent_file, 'timeout': timeout})
        return self.responses[path].pop(0)

    def paths(self):
        return [c['path'] for c in self.calls]


@override_settings(AI_SERVER_URL='http://ai.test', AI_SERVER_TOKEN='internal-token', BACKGROUND_JOBS_SYNC=True)
class MaterialUploadTests(APITestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.override = override_settings(TEMP_UPLOAD_DIR=self.tmp)
        self.override.enable()
        self.url = reverse('material-create')
        self.user = User.objects.create_user(email='jimin@gmail.com', google_sub='sub-jimin', nickname='지민')
        self.login(self.user)

    def tearDown(self):
        self.override.disable()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def login(self, user):
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {RefreshToken.for_user(user).access_token}')

    def upload(self, run_job=True, ai=None, **fields):
        """업로드하고, run_job이면 커밋 뒤 백그라운드 작업까지 실행"""
        ai = ai or FakeAiServer()
        with patch('common.ai_client.requests.post', side_effect=ai):
            if run_job:
                with self.captureOnCommitCallbacks(execute=True):
                    response = self.client.post(self.url, fields, format='multipart')
            else:
                response = self.client.post(self.url, fields, format='multipart')
        return response, ai

    def pdf(self, name='word2vec.pdf', content=b'%PDF-1.4 fake'):
        return SimpleUploadedFile(name, content, content_type='application/pdf')

    def assert_error(self, response, http_status, code):
        self.assertEqual(response.status_code, http_status)
        error = response.json()['error']
        self.assertEqual(error['code'], code)
        self.assertEqual(error['request_id'], response.headers['X-Request-ID'])

    # ------------------------------------------------------------------
    # 1. 성공
    # ------------------------------------------------------------------
    def test_accepts_and_returns_202_before_processing(self):
        response, ai = self.upload(run_job=False, title='  word2vec  ', text='word2vec은 ...')

        self.assertEqual(response.status_code, status.HTTP_202_ACCEPTED)
        data = response.json()
        self.assertEqual(data, {'id': data['id'], 'title': 'word2vec', 'status': 'processing'})
        self.assertEqual(ai.calls, [])
        # 원본은 DB가 아니라 임시 저장소에
        self.assertIsNotNone(storage.find_original(data['id']))
        material = Material.objects.get(pk=data['id'])
        self.assertEqual(material.source_type, 'text')
        self.assertIsNone(material.summary)

    def test_text_material_is_processed(self):
        response, ai = self.upload(title='word2vec', text='word2vec은 단어를 벡터로 ...')

        material = Material.objects.get(pk=response.json()['id'])
        self.assertEqual(material.status, 'ready')
        self.assertEqual(material.summary, SUMMARY)
        self.assertIsNotNone(material.processed_at)
        self.assertIsNone(material.error)
        self.assertEqual(
            list(Term.objects.filter(material=material).values_list('name', 'definition', 'display_order')),
            [('분산 표현', TERMS[0]['definition'], 1), ('CBOW', TERMS[1]['definition'], 2)],
        )
        # 원본 폐기
        self.assertIsNotNone(material.original_deleted_at)
        self.assertFalse(storage.material_dir(material.id).exists())

        # AI-1 → AI-2 순서, 헤더, 요청 ID
        self.assertEqual(ai.paths(), ['/materials/terms', '/materials/summary'])
        request_id = response.headers['X-Request-ID']
        for call in ai.calls:
            self.assertEqual(call['headers'], {'X-Internal-Token': 'internal-token', 'X-Request-ID': request_id})
            self.assertEqual(call['timeout'], 180)
            self.assertEqual(call['data']['title'], 'word2vec')
            self.assertEqual(call['data']['text'], 'word2vec은 단어를 벡터로 ...')
            self.assertIsNone(call['file'])
        self.assertEqual(json.loads(ai.calls[1]['data']['terms']), TERMS)

    def test_pdf_file_is_sent_as_is(self):
        response, ai = self.upload(title='word2vec', file=self.pdf())

        material = Material.objects.get(pk=response.json()['id'])
        self.assertEqual(material.status, 'ready')
        self.assertEqual((material.source_type, material.file_name, material.file_ext), ('file', 'word2vec.pdf', 'pdf'))
        for call in ai.calls:
            self.assertEqual(call['file'], ('word2vec.pdf', b'%PDF-1.4 fake', 'application/pdf'))
            self.assertNotIn('text', call['data'])

    def test_pptx_is_converted_to_pdf(self):
        def fake_soffice(args, **kwargs):
            source = Path(args[-1])
            source.with_suffix('.pdf').write_bytes(b'%PDF converted')

            class Result:
                returncode = 0
            return Result()

        with patch('materials.conversion.subprocess.run', side_effect=fake_soffice) as run:
            response, ai = self.upload(
                title='슬라이드', file=SimpleUploadedFile('lecture.pptx', b'pptx-bytes'),
            )

        self.assertEqual(Material.objects.get(pk=response.json()['id']).status, 'ready')
        self.assertIn('--convert-to', run.call_args.args[0])
        for call in ai.calls:
            self.assertEqual(call['file'], ('lecture.pdf', b'%PDF converted', 'application/pdf'))

    # ------------------------------------------------------------------
    # 2. 백그라운드 실패
    # ------------------------------------------------------------------
    def test_retries_once_then_succeeds(self):
        ai = FakeAiServer(terms=[ai_error(), ok_terms()])

        response, ai = self.upload(ai=ai, title='word2vec', text='...')

        self.assertEqual(Material.objects.get(pk=response.json()['id']).status, 'ready')
        self.assertEqual(ai.paths(), ['/materials/terms', '/materials/terms', '/materials/summary'])

    def test_fails_after_second_ai_error(self):
        ai = FakeAiServer(summary=[ai_error('LLM_ERROR', 502), ai_error('LLM_ERROR', 502)])

        response, ai = self.upload(ai=ai, title='word2vec', text='...')

        material = Material.objects.get(pk=response.json()['id'])
        self.assertEqual(material.status, 'failed')
        self.assertEqual(
            material.error,
            {'code': 'AI_ERROR', 'message': 'AI 처리에 실패했어요.', 'request_id': response.headers['X-Request-ID']},
        )
        self.assertIsNone(material.processed_at)
        # 실패해도 원본은 지움
        self.assertIsNotNone(material.original_deleted_at)
        self.assertFalse(storage.material_dir(material.id).exists())

    def test_unreadable_material_is_not_retried(self):
        ai = FakeAiServer(terms=[ai_error('UNREADABLE_MATERIAL', 422)])

        response, ai = self.upload(ai=ai, title='빈 PDF', file=self.pdf())

        material = Material.objects.get(pk=response.json()['id'])
        self.assertEqual(material.status, 'failed')
        self.assertEqual(material.error['code'], 'UNREADABLE_MATERIAL')
        self.assertEqual(ai.paths(), ['/materials/terms'])

    def test_libreoffice_missing(self):
        with patch('materials.conversion.subprocess.run', side_effect=FileNotFoundError):
            response, ai = self.upload(title='문서', file=SimpleUploadedFile('notes.docx', b'docx'))

        material = Material.objects.get(pk=response.json()['id'])
        self.assertEqual(material.status, 'failed')
        self.assertEqual(material.error['code'], 'AI_ERROR')
        self.assertEqual(ai.calls, [])
        self.assertFalse(storage.material_dir(material.id).exists())

    def test_ai_server_not_configured(self):
        with override_settings(AI_SERVER_URL=''):
            response, ai = self.upload(title='word2vec', text='...')

        material = Material.objects.get(pk=response.json()['id'])
        self.assertEqual(material.status, 'failed')
        self.assertEqual(material.error['code'], 'AI_ERROR')

    def test_user_deleted_during_processing_ends_quietly(self):
        ai = FakeAiServer()
        original_call = ai.__call__

        def delete_user_then_answer(*args, **kwargs):
            User.objects.filter(pk=self.user.pk).delete()
            return original_call(*args, **kwargs)

        with patch('common.ai_client.requests.post', side_effect=delete_user_then_answer):
            with self.captureOnCommitCallbacks(execute=True):
                response = self.client.post(self.url, {'title': 'word2vec', 'text': '...'}, format='multipart')

        material_id = response.json()['id']
        self.assertFalse(Material.objects.filter(pk=material_id).exists())
        self.assertFalse(storage.material_dir(material_id).exists())

    # ------------------------------------------------------------------
    # 3. 요청 에러
    # ------------------------------------------------------------------
    def test_validation_errors(self):
        cases = {
            'no title': {'text': '...'},
            'blank title': {'title': '   ', 'text': '...'},
            'title too long': {'title': '가' * 101, 'text': '...'},
            'neither file nor text': {'title': 'word2vec'},
            'blank text': {'title': 'word2vec', 'text': '   '},
            'both file and text': {'title': 'word2vec', 'text': '...', 'file': self.pdf()},
        }
        for name, fields in cases.items():
            with self.subTest(name):
                response, _ = self.upload(run_job=False, **fields)

                self.assert_error(response, status.HTTP_400_BAD_REQUEST, 'VALIDATION_ERROR')
        self.assertFalse(Material.objects.exists())

    def test_unsupported_file_type(self):
        for name in ['virus.exe', 'archive.zip', 'noextension']:
            with self.subTest(name):
                response, _ = self.upload(run_job=False, title='x', file=SimpleUploadedFile(name, b'data'))

                self.assert_error(response, status.HTTP_400_BAD_REQUEST, 'UNSUPPORTED_FILE_TYPE')
        self.assertFalse(Material.objects.exists())

    def test_supported_extensions_are_case_insensitive(self):
        response, _ = self.upload(run_job=False, title='사진', file=SimpleUploadedFile('BOARD.JPG', b'jpg'))

        self.assertEqual(response.status_code, status.HTTP_202_ACCEPTED)
        self.assertEqual(Material.objects.get().file_ext, 'jpg')

    @override_settings(MAX_UPLOAD_MB=0)
    def test_file_too_large(self):
        response, _ = self.upload(run_job=False, title='큰 파일', file=self.pdf())

        self.assert_error(response, status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, 'FILE_TOO_LARGE')
        self.assertFalse(Material.objects.exists())

    def test_nickname_required(self):
        user = User.objects.create_user(email='new@gmail.com', google_sub='sub-new')
        self.login(user)

        response, _ = self.upload(run_job=False, title='word2vec', text='...')

        self.assert_error(response, status.HTTP_409_CONFLICT, 'NICKNAME_REQUIRED')

    def test_requires_login(self):
        self.client.credentials()

        response, _ = self.upload(run_job=False, title='word2vec', text='...')

        self.assert_error(response, status.HTTP_401_UNAUTHORIZED, 'UNAUTHORIZED')

    # ------------------------------------------------------------------
    # 4. 회원 탈퇴(06)와의 연동
    # ------------------------------------------------------------------
    def test_withdrawal_removes_originals_of_processing_materials(self):
        response, _ = self.upload(run_job=False, title='word2vec', text='...')
        material_id = response.json()['id']
        self.assertTrue(storage.material_dir(material_id).exists())

        with self.captureOnCommitCallbacks(execute=True):
            self.client.delete(reverse('users-me'))

        self.assertFalse(Material.objects.filter(pk=material_id).exists())
        self.assertFalse(storage.material_dir(material_id).exists())
