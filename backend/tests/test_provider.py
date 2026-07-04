from app.core.llm.provider import strip_json_code_fence


def test_strip_json_code_fence_removes_json_labeled_fence():
    text = '```json\n{"a": 1}\n```'
    assert strip_json_code_fence(text) == '{"a": 1}'


def test_strip_json_code_fence_removes_bare_fence():
    text = '```\n{"a": 1}\n```'
    assert strip_json_code_fence(text) == '{"a": 1}'


def test_strip_json_code_fence_leaves_unfenced_text_unchanged():
    text = '{"a": 1}'
    assert strip_json_code_fence(text) == '{"a": 1}'


def test_strip_json_code_fence_handles_surrounding_whitespace():
    text = '  \n```json\n{"a": 1}\n```\n  '
    assert strip_json_code_fence(text) == '{"a": 1}'
