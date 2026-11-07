from django.db import models


class Persona(models.Model):
    """ERD의 personas 테이블. 학생 AI 3명(하늘·민준·서연)으로 고정, 마이그레이션 시드로 넣습니다.

    지우지 않습니다 (lessons.persona_id가 PROTECT).
    system_prompt는 프론트엔드에 내려주지 않습니다.
    """

    code = models.CharField(max_length=20, unique=True)
    name = models.CharField(max_length=20)
    grade_label = models.CharField(max_length=10)
    description = models.TextField()
    system_prompt = models.TextField()
    display_order = models.IntegerField()

    class Meta:
        db_table = 'personas'
        ordering = ['display_order']

    def __str__(self):
        return f'{self.name} ({self.grade_label})'
