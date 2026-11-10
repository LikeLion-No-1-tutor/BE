"""
URL configuration for line1_thon project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/6.1/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.conf import settings
from django.urls import path, include

urlpatterns = [
    path('', include('accounts.urls')),
    path('', include('personas.urls')),
    path('', include('materials.urls')),
    path('', include('lessons.urls')),
    path('', include('exams.urls')),
]

# API 문서. 운영 서버에는 열지 않습니다 (settings.API_DOCS).
if settings.API_DOCS:
    from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView

    urlpatterns += [
        path('api/schema', SpectacularAPIView.as_view(), name='api-schema'),
        path('api/docs', SpectacularSwaggerView.as_view(url_name='api-schema'), name='api-docs'),
    ]

# DEBUG=False일 때 DRF 밖의 404·500도 공통 에러 형식으로
handler404 = 'common.views.not_found'
handler500 = 'common.views.server_error'
