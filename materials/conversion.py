"""PPT·DOCX → PDF 변환 (LibreOffice headless).

LibreOffice가 서버에 설치돼 있어야 합니다. 실행 파일 경로는 settings.LIBREOFFICE_PATH (기본 soffice).
"""
import subprocess
from pathlib import Path

from django.conf import settings

from common.ai_client import AiError

CONVERT_TO_PDF_EXTS = {'ppt', 'pptx', 'doc', 'docx'}
CONVERT_TIMEOUT = 120  # 초


def convert_to_pdf(path: Path) -> Path:
    """같은 폴더에 PDF를 만들고 경로를 돌려줍니다."""
    try:
        result = subprocess.run(
            [
                settings.LIBREOFFICE_PATH, '--headless', '--norestore',
                '--convert-to', 'pdf', '--outdir', str(path.parent), str(path),
            ],
            capture_output=True,
            timeout=CONVERT_TIMEOUT,
            check=False,
        )
    except FileNotFoundError:
        # 서버 설정 문제. 사용자 입장에서는 '다시 시도'할 문제라 AI_ERROR로 묶음
        raise AiError('AI_ERROR', 'LibreOffice를 찾을 수 없어요.', 'LIBREOFFICE_NOT_FOUND')
    except subprocess.TimeoutExpired:
        raise AiError('AI_ERROR', 'PDF 변환 시간이 초과됐어요.', 'CONVERT_TIMEOUT')

    pdf_path = path.with_suffix('.pdf')
    if result.returncode != 0 or not pdf_path.exists():
        # 깨진 파일, 암호가 걸린 파일 등
        raise AiError('UNREADABLE_MATERIAL', '파일을 PDF로 바꾸지 못했어요.', 'CONVERT_FAILED')
    return pdf_path
