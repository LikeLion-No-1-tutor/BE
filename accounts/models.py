from django.contrib.auth.base_user import AbstractBaseUser, BaseUserManager
from django.db import models


class UserManager(BaseUserManager):
    use_in_migrations = True

    def create_user(self, email, google_sub, **extra_fields):
        """구글 로그인으로 가입하는 사용자. 비밀번호·관리자 계정은 없습니다."""
        if not email:
            raise ValueError('email이 필요해요.')
        if not google_sub:
            raise ValueError('google_sub이 필요해요.')
        user = self.model(email=self.normalize_email(email), google_sub=google_sub, **extra_fields)
        user.save(using=self._db)
        return user


class User(AbstractBaseUser):
    """ERD의 users 테이블. 구글 로그인만 쓰므로 ERD의 컬럼만 둡니다."""

    email = models.EmailField(max_length=254, unique=True)
    google_sub = models.CharField(max_length=64, unique=True)
    nickname = models.CharField(max_length=20, null=True, blank=True)
    onboarding_completed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    last_login_at = models.DateTimeField(null=True, blank=True)

    # AbstractBaseUser가 만드는 컬럼 중 쓰지 않는 것은 뺍니다.
    password = None  # 비밀번호 로그인 없음
    last_login = None  # ERD의 last_login_at을 씀

    objects = UserManager()

    USERNAME_FIELD = 'email'
    EMAIL_FIELD = 'email'
    REQUIRED_FIELDS = []

    class Meta:
        db_table = 'users'

    def __str__(self):
        return self.email

    @property
    def onboarding_completed(self):
        return self.onboarding_completed_at is not None
