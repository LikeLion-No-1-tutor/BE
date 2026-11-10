from drf_spectacular.openapi import AutoSchema as SpectacularAutoSchema

from .docs_examples import COMPONENTS


class AutoSchema(SpectacularAutoSchema):
    """뷰의 docstring은 개발자용 메모라 문서 설명으로 쓰지 않습니다. 설명은 extend_schema에만 적습니다."""

    def get_description(self):
        return ''


def drop_component_descriptions(result, generator, request, public):
    """serializer의 docstring도 개발자용 메모라 문서에서 뺍니다. 필드 설명(help_text)은 남깁니다."""
    for component in result.get('components', {}).get('schemas', {}).values():
        component.pop('description', None)
    return result


def add_field_examples(result, generator, request, public):
    """필드마다 예시 값을 넣습니다 (common/docs_examples.py). Swagger가 "string", 0 대신 이 값을 보여 줍니다."""
    for name, component in result.get('components', {}).get('schemas', {}).items():
        examples = COMPONENTS.get(name, {})
        for field, schema in component.get('properties', {}).items():
            if field in examples:
                schema['example'] = examples[field]
    return result
