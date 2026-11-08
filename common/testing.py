"""테스트에서 같이 쓰는 함수. 다른 API를 거치지 않고 데이터를 바로 만듭니다."""
from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework.test import APIClient

from materials.models import Material, Term


def make_user(email='teacher@gmail.com', nickname='선생님', **fields):
    """구글 로그인을 거치지 않고 사용자를 만듭니다. nickname=None이면 닉네임 입력 전 사용자."""
    google_sub = fields.pop('google_sub', f'sub-{email}')
    return get_user_model().objects.create_user(email=email, google_sub=google_sub, nickname=nickname, **fields)


def client_for(user):
    """user로 로그인한 APIClient. 로그인 API를 부르지 않습니다."""
    client = APIClient()
    client.force_authenticate(user)
    return client


def make_ready_material(user, title='word2vec', terms=('분산 표현', '원핫 표현'), summary='요약정리 내용'):
    """자료 정리가 끝난 상태의 자료와 용어를 바로 만듭니다. AI 서버를 거치지 않습니다.

    terms: 용어 이름 목록. 정의는 '<이름>의 정의'로 채웁니다.
    """
    now = timezone.now()
    material = Material.objects.create(
        user=user,
        title=title,
        source_type=Material.SourceType.TEXT,
        summary=summary,
        status=Material.Status.READY,
        original_deleted_at=now,
        processed_at=now,
    )
    Term.objects.bulk_create(
        Term(material=material, name=name, definition=f'{name}의 정의', display_order=order)
        for order, name in enumerate(terms, start=1)
    )
    return material
