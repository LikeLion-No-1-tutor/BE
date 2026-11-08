"""목록 페이지 ?page=&size= → {items, page, size, total}"""
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import path
from rest_framework.views import APIView

from .pagination import PagePagination
from .testing import make_user


class NumbersView(APIView):
    authentication_classes = []
    permission_classes = []

    def get(self, request):
        queryset = get_user_model().objects.order_by('id').values_list('id', flat=True)
        paginator = PagePagination()
        page = paginator.paginate_queryset(queryset, request, view=self)
        return paginator.get_paginated_response(page)


urlpatterns = [path('numbers', NumbersView.as_view())]


@override_settings(ROOT_URLCONF='common.test_pagination')
class PaginationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.ids = [make_user(email=f'u{i}@gmail.com').id for i in range(5)]

    def test_default(self):
        body = self.client.get('/numbers').json()
        self.assertEqual(body, {'items': self.ids, 'page': 1, 'size': 20, 'total': 5})

    def test_page_and_size(self):
        body = self.client.get('/numbers?page=2&size=2').json()
        self.assertEqual(body, {'items': self.ids[2:4], 'page': 2, 'size': 2, 'total': 5})

    def test_past_last_page_is_empty(self):
        body = self.client.get('/numbers?page=9&size=2').json()
        self.assertEqual(body['items'], [])
        self.assertEqual(body['total'], 5)

    def test_size_is_capped(self):
        self.assertEqual(self.client.get('/numbers?size=1000').json()['size'], 100)

    def test_invalid_values_are_400(self):
        for query in ['page=0', 'page=-1', 'page=abc', 'size=0', 'size=1.5']:
            with self.subTest(query=query):
                response = self.client.get(f'/numbers?{query}')
                self.assertEqual(response.status_code, 400, response.content)
                self.assertEqual(response.json()['error']['code'], 'VALIDATION_ERROR')
