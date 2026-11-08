"""09. 자료 정리 상태 GET /api/materials/{material_id}"""
from django.contrib.auth import get_user_model
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from materials.models import Material, Term

User = get_user_model()


class MaterialStatusTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(email='t@gmail.com', google_sub='sub-t', nickname='선생님')
        self.client.force_authenticate(self.user)
        self.material = Material.objects.create(
            user=self.user, title='word2vec', source_type=Material.SourceType.FILE,
            file_name='밑바닥딥러닝2_word2vec.pdf', file_ext='pdf',
        )

    def get(self, material_id=None):
        return self.client.get(reverse('material-detail', args=[material_id or self.material.id]))

    def update(self, **fields):
        Material.objects.filter(pk=self.material.pk).update(**fields)

    def add_terms(self, *names):
        Term.objects.bulk_create(
            Term(material=self.material, name=name, definition=f'{name}의 정의', display_order=i)
            for i, name in enumerate(names, start=1)
        )

    def steps(self):
        response = self.get()
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.content)
        return response.json()['steps']

    # 응답 모양 ------------------------------------------------------------

    def test_response_while_processing(self):
        self.assertEqual(self.get().json(), {
            'id': self.material.id,
            'title': 'word2vec',
            'source_type': 'file',
            'file_name': '밑바닥딥러닝2_word2vec.pdf',
            'status': 'processing',
            'steps': {'read': 'done', 'terms': 'running', 'summary': 'pending', 'original_deleted': 'pending'},
            'term_count': 0,
            'error': None,
        })

    def test_text_material(self):
        material = Material.objects.create(user=self.user, title='메모', source_type=Material.SourceType.TEXT)
        body = self.get(material.id).json()
        self.assertEqual((body['source_type'], body['file_name']), ('text', None))

    # 단계별 진행 (명세의 계산표) --------------------------------------------

    def test_terms_done_summary_running(self):
        self.add_terms('분산 표현', 'CBOW')
        self.assertEqual(self.steps(), {'read': 'done', 'terms': 'done', 'summary': 'running',
                                        'original_deleted': 'pending'})
        self.assertEqual(self.get().json()['term_count'], 2)

    def test_summary_done_deleting_original(self):
        self.add_terms('분산 표현')
        self.update(summary='# 요약')
        self.assertEqual(self.steps(), {'read': 'done', 'terms': 'done', 'summary': 'done',
                                        'original_deleted': 'running'})

    def test_ready(self):
        self.add_terms('분산 표현')
        now = timezone.now()
        self.update(summary='# 요약', original_deleted_at=now, status=Material.Status.READY, processed_at=now)
        body = self.get().json()
        self.assertEqual(body['status'], 'ready')
        self.assertEqual(set(body['steps'].values()), {'done'})

    def test_failed_at_terms(self):
        error = {'code': 'UNREADABLE_MATERIAL', 'message': '자료에서 내용을 읽을 수 없어요.', 'request_id': 'r'}
        self.update(status=Material.Status.FAILED, error=error, original_deleted_at=timezone.now())
        body = self.get().json()
        self.assertEqual(body['status'], 'failed')
        self.assertEqual(body['error'], error)
        self.assertEqual(body['steps'], {'read': 'done', 'terms': 'pending', 'summary': 'pending',
                                         'original_deleted': 'done'})

    def test_failed_at_summary(self):
        self.add_terms('분산 표현')
        self.update(status=Material.Status.FAILED, original_deleted_at=timezone.now(),
                    error={'code': 'AI_ERROR', 'message': 'AI 처리에 실패했어요.', 'request_id': 'r'})
        self.assertEqual(self.steps(), {'read': 'done', 'terms': 'done', 'summary': 'pending',
                                        'original_deleted': 'done'})

    # 숨기는 값 --------------------------------------------------------------

    def test_definitions_and_summary_are_hidden(self):
        self.add_terms('분산 표현')
        self.update(summary='비밀 요약정리 내용', status=Material.Status.READY)
        text = self.get().content.decode()
        self.assertNotIn('의 정의', text)
        self.assertNotIn('비밀 요약정리 내용', text)

    # 에러 -------------------------------------------------------------------

    def test_unknown_material_is_404(self):
        response = self.get(999999)
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(response.json()['error']['code'], 'NOT_FOUND')
        self.assertEqual(response.json()['error']['message'], '자료를 찾을 수 없어요.')

    def test_other_users_material_is_403(self):
        other = User.objects.create_user(email='o@gmail.com', google_sub='sub-o', nickname='남')
        self.client.force_authenticate(other)
        response = self.get()
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(response.json()['error']['code'], 'FORBIDDEN')

    def test_not_logged_in_is_401(self):
        self.client.force_authenticate(None)
        response = self.get()
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertEqual(response.json()['error']['code'], 'UNAUTHORIZED')

    def test_nickname_required_is_409(self):
        self.user.nickname = None
        self.user.save(update_fields=['nickname'])
        response = self.get()
        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)
        self.assertEqual(response.json()['error']['code'], 'NICKNAME_REQUIRED')

    def test_request_id_header_matches_body(self):
        response = self.get(999999)
        self.assertEqual(response.headers['X-Request-ID'], response.json()['error']['request_id'])
