import uuid
from django.conf import settings
from django.contrib.auth import get_user_model
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework_simplejwt.tokens import RefreshToken

from google.oauth2 import id_token
from google.auth.transport import requests as google_requests

from .serializers import GoogleLoginRequestSerializer, UserResponseSerializer

User = get_user_model()

class GoogleLoginView(APIView):
    permission_classes = []  # 인증 필요 없음

    def post(self, request):
        request_id = str(uuid.uuid4())
        headers = {'X-Request-ID': request_id}

        # 1. 입력값 검증 (id_token 누락 체크)
        serializer = GoogleLoginRequestSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(
                {
                    "error": {
                        "code": "VALIDATION_ERROR",
                        "message": "id_token이 필요해요.",
                        "request_id": request_id
                    }
                },
                status=status.HTTP_400_BAD_REQUEST,
                headers=headers
            )

        token = serializer.validated_data['id_token']

        # 2. 구글 ID 토큰 검증
        try:
            # GOOGLE_CLIENT_ID는 settings.py에 설정해둔 구글 클라이언트 ID입니다.
            id_info = id_token.verify_oauth2_token(
                token, 
                google_requests.Request(), 
                settings.GOOGLE_CLIENT_ID
            )
        except ValueError:
            # 토큰 만료, 서명 위조 등의 검증 실패
            return Response(
                {
                    "error": {
                        "code": "UNAUTHORIZED",
                        "message": "구글 로그인 정보를 확인할 수 없어요.",
                        "request_id": request_id
                    }
                },
                status=status.HTTP_401_UNAUTHORIZED,
                headers=headers
            )

        google_sub = id_info.get('sub')
        email = id_info.get('email')

        # 3. 유저 조회 또는 생성 (is_new_user 판단)
        user = User.objects.filter(google_sub=google_sub).first()
        is_new_user = False

        if not user:
            # sub로 찾지 못했으나 이메일이 기존에 존재하는 경우 처리 혹은 생성
            user = User.objects.filter(email=email).first()
            if user:
                user.google_sub = google_sub
                user.save()
            else:
                user = User.objects.create_user(
                    username=email, # AbstractUser 기본 필드 충돌 방지용
                    email=email,
                    google_sub=google_sub
                )
                is_new_user = True

        # 4. last_login_at 갱신 (auto_now=True 설정 시 save 호출로 자동 갱신)
        user.save()

        # 5. SimpleJWT 토큰 발급
        refresh = RefreshToken.for_user(user)

        # 6. 응답 데이터 구성
        user_data = UserResponseSerializer(user).data

        response_payload = {
            "access_token": str(refresh.access_token),
            "refresh_token": str(refresh),
            "is_new_user": is_new_user,
            "user": user_data
        }

        return Response(response_payload, status=status.HTTP_200_OK, headers=headers)
