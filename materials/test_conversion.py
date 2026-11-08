"""PPT·DOCX → PDF 변환: 변환마다 LibreOffice 프로필을 따로 쓰는지."""
import shutil
import tempfile
from pathlib import Path
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase, override_settings
from django.urls import reverse
from rest_framework.test import APITestCase

from materials import storage
from materials.conversion import PROFILE_DIR_NAME, convert_to_pdf
from materials.models import Material
from materials.tests import FakeAiServer

User = get_user_model()


def fake_soffice(args, **kwargs):
    """LibreOffice 흉내: 프로필 폴더와 PDF를 만듦"""
    profile = next(a for a in args if a.startswith('-env:UserInstallation='))
    profile_path = Path(profile.split('file://', 1)[1].replace('%20', ' '))
    profile_path.mkdir(parents=True, exist_ok=True)
    (profile_path / 'registrymodifications.xcu').write_text('<x/>')
    Path(args[-1]).with_suffix('.pdf').write_bytes(b'%PDF converted')

    class Result:
        returncode = 0
    return Result()


class ConvertCommandTests(SimpleTestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def convert(self, folder):
        folder.mkdir(parents=True)
        source = folder / 'original.pptx'
        source.write_bytes(b'pptx')
        with patch('materials.conversion.subprocess.run', side_effect=fake_soffice) as run:
            pdf = convert_to_pdf(source)
        return run.call_args.args[0], source, pdf

    def test_profile_is_inside_the_material_folder(self):
        args, source, pdf = self.convert(self.tmp / '12')

        expected = (self.tmp / '12' / PROFILE_DIR_NAME).resolve().as_uri()
        self.assertEqual(args[1], f'-env:UserInstallation={expected}')
        self.assertEqual(args[-1], str(source))  # 변환할 파일은 맨 끝 그대로
        self.assertEqual(pdf, source.with_suffix('.pdf'))

    def test_each_material_gets_its_own_profile(self):
        first, _, _ = self.convert(self.tmp / '1')
        second, _, _ = self.convert(self.tmp / '2')
        self.assertNotEqual(first[1], second[1])

    def test_folder_with_spaces_becomes_a_valid_uri(self):
        args, _, _ = self.convert(self.tmp / 'upload dir' / '3')
        self.assertIn('upload%20dir', args[1])
        self.assertNotIn(' ', args[1])


# 작업을 커밋 직후 바로 실행 (스레드 풀이든 DB 큐든 같은 테스트로)
@override_settings(
    AI_SERVER_URL='http://ai.test', AI_SERVER_TOKEN='internal-token', BACKGROUND_JOBS_SYNC=True,
    TASKS={'default': {'BACKEND': 'django.tasks.backends.immediate.ImmediateBackend'}},
)
class ConvertCleanupTests(APITestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.override = override_settings(TEMP_UPLOAD_DIR=self.tmp)
        self.override.enable()
        self.addCleanup(self.override.disable)
        self.addCleanup(shutil.rmtree, self.tmp, True)
        user = User.objects.create_user(email='jimin@gmail.com', google_sub='sub-jimin', nickname='지민')
        self.client.force_authenticate(user)

    def test_profile_is_deleted_with_the_original(self):
        with patch('materials.conversion.subprocess.run', side_effect=fake_soffice), \
                patch('common.ai_client.requests.post', side_effect=FakeAiServer()), \
                self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(
                reverse('material-create'),
                {'title': '슬라이드', 'file': SimpleUploadedFile('lecture.pptx', b'pptx')}, format='multipart',
            )

        material = Material.objects.get(pk=response.json()['id'])
        self.assertEqual(material.status, Material.Status.READY)
        self.assertFalse(storage.material_dir(material.id).exists())  # 원본, PDF, 프로필 모두
