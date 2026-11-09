"""원본 자료 임시 저장소.

원본은 DB에 저장하지 않고 TEMP_UPLOAD_DIR/<material_id>/ 아래에만 둡니다.
자료 정리가 끝나면(성공·실패 상관없이) 폴더째 지웁니다 (원본 폐기 원칙: 저작권·서버 용량).
"""
import shutil
from pathlib import Path

from django.conf import settings

TEXT_FILE_NAME = 'input.txt'


def material_dir(material_id):
    return Path(settings.TEMP_UPLOAD_DIR) / str(material_id)


def save_file(material_id, uploaded_file, ext):
    folder = material_dir(material_id)
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f'original.{ext}'
    with open(path, 'wb') as out:
        for chunk in uploaded_file.chunks():
            out.write(chunk)
    return path


def save_text(material_id, text):
    folder = material_dir(material_id)
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / TEXT_FILE_NAME
    path.write_text(text, encoding='utf-8')
    return path


def find_original(material_id):
    """저장한 원본 파일 경로. 없으면 None"""
    folder = material_dir(material_id)
    if not folder.is_dir():
        return None
    for path in sorted(folder.iterdir()):
        if path.name == TEXT_FILE_NAME or path.name.startswith('original.'):
            return path
    return None


def delete(material_id):
    """원본(과 변환한 PDF)을 폴더째 지웁니다. 이미 없으면 아무것도 하지 않습니다."""
    shutil.rmtree(material_dir(material_id), ignore_errors=True)
