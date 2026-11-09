from django.conf import settings
from django.db import models


class Material(models.Model):
    """ERD의 materials 테이블 (학습 자료).

    원본 파일은 DB에 저장하지 않습니다. 임시 저장소에만 두었다가 정리가 끝나면(실패해도) 지웁니다.
    summary는 프론트엔드와 학생 AI에 절대 내려주지 않습니다.
    """

    class SourceType(models.TextChoices):
        FILE = 'file'
        TEXT = 'text'

    class Status(models.TextChoices):
        PROCESSING = 'processing'
        READY = 'ready'
        FAILED = 'failed'

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='materials')
    title = models.CharField(max_length=100)
    source_type = models.CharField(max_length=10, choices=SourceType.choices)
    file_name = models.CharField(max_length=255, null=True, blank=True)
    file_ext = models.CharField(max_length=10, null=True, blank=True)
    summary = models.TextField(null=True, blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PROCESSING)
    error = models.JSONField(null=True, blank=True)
    original_deleted_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    processed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'materials'

    def __str__(self):
        return self.title


class Term(models.Model):
    """ERD의 terms 테이블 (자료별 용어 체크리스트).

    definition은 프론트엔드와 학생 AI에 절대 내려주지 않습니다.
    """

    material = models.ForeignKey(Material, on_delete=models.CASCADE, related_name='terms')
    name = models.CharField(max_length=100)
    definition = models.TextField()
    display_order = models.IntegerField()

    class Meta:
        db_table = 'terms'
        ordering = ['display_order']

    def __str__(self):
        return self.name
