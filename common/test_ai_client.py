"""AI 서버 호출 규칙 (common/ai_client.py): 타임아웃, 재시도, 응답 모양 확인"""
import io
from unittest.mock import patch

import requests
from django.test import SimpleTestCase, override_settings

from common import ai_client
from common.ai_client import AiError
from materials.tests import FakeResponse

RID = '3f2a9c1e-8b4d-4e7a-9f10-2c6b5d8e1a47'


def ok(body=None):
    return FakeResponse(200, {'value': 1, **(body or {})})


def failure(code='LLM_ERROR', http=502):
    return FakeResponse(http, {'error': {'code': code, 'message': '...'}})


def take_value(body):
    return body['value']


@override_settings(AI_SERVER_URL='http://ai.test/', AI_SERVER_TOKEN='token')
class AiClientTests(SimpleTestCase):
    def setUp(self):
        patcher = patch('common.ai_client.requests.post')
        self.post = patcher.start()
        self.addCleanup(patcher.stop)

    def call(self, path='/x', **kwargs):
        return ai_client.call(path, json={}, request_id=RID, user_id=7, **kwargs)

    def assert_raises_ai_error(self, code, original, level='ERROR', **kwargs):
        with self.assertLogs('common.ai_client', level=level), self.assertRaises(AiError) as ctx:
            self.call(**kwargs)
        self.assertEqual((ctx.exception.code, ctx.exception.original_code), (code, original))

    # 타임아웃과 헤더 ---------------------------------------------------------

    def test_background_is_the_default_and_waits_180_seconds(self):
        self.post.return_value = ok()
        self.call()
        self.assertEqual(self.post.call_args.kwargs['timeout'], 180)

    def test_realtime_waits_30_seconds(self):
        self.post.return_value = ok()
        self.call(mode=ai_client.REALTIME)
        self.assertEqual(self.post.call_args.kwargs['timeout'], 30)

    def test_url_and_headers(self):
        self.post.return_value = ok()
        self.call('/lessons/note')
        self.assertEqual(self.post.call_args.args[0], 'http://ai.test/lessons/note')
        self.assertEqual(self.post.call_args.kwargs['headers'], {'X-Internal-Token': 'token', 'X-Request-ID': RID})

    # 재시도 ----------------------------------------------------------------

    def test_background_retries_once_and_succeeds(self):
        self.post.side_effect = [failure(), ok()]
        with self.assertLogs('common.ai_client', level='INFO') as logs:
            body = self.call()
        self.assertEqual(body['value'], 1)
        self.assertEqual([(r.attempt, r.levelname) for r in logs.records], [(1, 'WARNING'), (2, 'INFO')])

    def test_background_gives_up_after_second_failure(self):
        self.post.return_value = failure('LLM_TIMEOUT', 504)
        with self.assertLogs('common.ai_client', level='INFO') as logs, self.assertRaises(AiError) as ctx:
            self.call()
        self.assertEqual((ctx.exception.code, ctx.exception.original_code), ('AI_ERROR', 'LLM_TIMEOUT'))
        self.assertEqual(self.post.call_count, 2)
        self.assertEqual([(r.attempt, r.levelname, r.status) for r in logs.records],
                         [(1, 'WARNING', 504), (2, 'ERROR', 504)])

    def test_realtime_does_not_retry(self):
        self.post.return_value = failure()
        self.assert_raises_ai_error('AI_ERROR', 'LLM_ERROR', mode=ai_client.REALTIME)
        self.assertEqual(self.post.call_count, 1)

    def test_unreadable_material_is_not_retried(self):
        self.post.return_value = failure('UNREADABLE_MATERIAL', 422)
        self.assert_raises_ai_error('UNREADABLE_MATERIAL', 'UNREADABLE_MATERIAL')
        self.assertEqual(self.post.call_count, 1)

    def test_timeout_and_connection_error_are_retried(self):
        for exc, original in [(requests.Timeout(), 'DJANGO_TIMEOUT'), (requests.ConnectionError(), 'ConnectionError')]:
            with self.subTest(original=original):
                self.post.reset_mock()
                self.post.side_effect = exc
                self.assert_raises_ai_error('AI_ERROR', original)
                self.assertEqual(self.post.call_count, 2)

    def test_file_is_read_from_the_start_on_retry(self):
        upload = io.BytesIO(b'%PDF-1.7')
        seen = []

        def read_and_fail_once(*args, **kwargs):
            seen.append(kwargs['files']['file'][1].read())
            return failure() if len(seen) == 1 else ok()

        self.post.side_effect = read_and_fail_once
        with self.assertLogs('common.ai_client', level='WARNING'):
            ai_client.call('/x', data={'title': 't'}, files={'file': ('a.pdf', upload, 'application/pdf')},
                           request_id=RID)
        self.assertEqual(seen, [b'%PDF-1.7', b'%PDF-1.7'])

    # 응답 모양 확인 ----------------------------------------------------------

    def test_parse_returns_its_value(self):
        self.post.return_value = ok()
        self.assertEqual(self.call(parse=take_value), 1)

    def test_bad_shape_is_retried_in_background(self):
        self.post.side_effect = [FakeResponse(200, {}), ok()]
        with self.assertLogs('common.ai_client', level='INFO') as logs:
            value = self.call(parse=take_value)
        self.assertEqual(value, 1)
        self.assertEqual(logs.records[0].error_code, 'INVALID_RESPONSE')

    def test_bad_shape_in_realtime_is_not_retried(self):
        self.post.return_value = FakeResponse(200, {})
        self.assert_raises_ai_error('AI_ERROR', 'INVALID_RESPONSE', mode=ai_client.REALTIME, parse=take_value)
        self.assertEqual(self.post.call_count, 1)

    def test_parse_errors_become_invalid_response(self):
        def raises(error):
            def parse(body):
                raise error
            return parse

        for error in [ValueError('x'), KeyError('x'), TypeError('x'), AttributeError('x')]:
            with self.subTest(error=type(error).__name__):
                self.post.reset_mock()
                self.post.return_value = ok()
                self.assert_raises_ai_error('AI_ERROR', 'INVALID_RESPONSE', parse=raises(error))
                self.assertEqual(self.post.call_count, 2)

    # 실시간 요청의 502 -------------------------------------------------------

    def test_to_api_error(self):
        api_error = AiError('AI_ERROR', '내부 사정', 'LLM_TIMEOUT').to_api_error()
        self.assertEqual((api_error.status_code, api_error.error_code, api_error.message),
                         (502, 'AI_ERROR', 'AI 처리에 실패했어요. 다시 시도해 주세요.'))

    # 설정·로그 ---------------------------------------------------------------

    def test_not_configured_does_not_call_or_retry(self):
        with override_settings(AI_SERVER_TOKEN=''):
            self.assert_raises_ai_error('AI_ERROR', 'AI_SERVER_NOT_CONFIGURED')
        self.post.assert_not_called()

    def test_log_has_usage_and_never_the_content(self):
        self.post.return_value = FakeResponse(200, {
            'secret_text': '사용자가 쓴 설명', 'usage': [{'input_tokens': 10, 'output_tokens': 2}],
        })
        with self.assertLogs('common.ai_client', level='INFO') as logs:
            self.call()
        record = logs.records[0]
        self.assertEqual((record.event, record.attempt, record.input_tokens, record.output_tokens, record.user_id),
                         ('ai_call', 1, 10, 2, 7))
        self.assertNotIn('사용자가 쓴 설명', ' '.join(logs.output))
