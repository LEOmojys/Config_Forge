"""Unit tests for provider-level JSON/content handling (no API calls)."""
from backend.providers.doubao_provider import _extract_json_content, _usage_dict


def test_extract_json_content_strips_fences():
    assert _extract_json_content('```json\n{"a": 1}\n```') == '{"a": 1}'
    assert _extract_json_content('```\n{"a": 1}\n```') == '{"a": 1}'
    assert _extract_json_content('  {"a": 1}  ') == '{"a": 1}'
    assert _extract_json_content('{"a": 1}') == '{"a": 1}'
    assert _extract_json_content('') == ''
    assert _extract_json_content(None) == ''


def test_extract_json_content_handles_unclosed_fence():
    # Model started a fence but never closed it: strip the opening marker.
    assert _extract_json_content('```json\n{"a": 1}') == '{"a": 1}'


def test_usage_dict_none_safe():
    assert _usage_dict(None) == {
        "prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0, "reasoning_tokens": 0,
    }

    class _Usage:
        prompt_tokens = 100
        completion_tokens = 50
        total_tokens = 150

    assert _usage_dict(_Usage()) == {
        "prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150, "reasoning_tokens": 0,
    }


def test_usage_dict_includes_reasoning_tokens():
    class _Details:
        reasoning_tokens = 7

    class _Usage:
        prompt_tokens = 100
        completion_tokens = 50
        total_tokens = 150
        completion_tokens_details = _Details()

    assert _usage_dict(_Usage()) == {
        "prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150, "reasoning_tokens": 7,
    }


def test_resolve_no_thinking_default_and_override(monkeypatch):
    from backend.providers.doubao_provider import _resolve_no_thinking

    monkeypatch.delenv("ARK_CODING_NO_THINKING", raising=False)
    assert _resolve_no_thinking() is True
    monkeypatch.setenv("ARK_CODING_NO_THINKING", "0")
    assert _resolve_no_thinking() is False
    monkeypatch.setenv("ARK_CODING_NO_THINKING", "1")
    assert _resolve_no_thinking() is True


def test_call_json_sends_thinking_disabled_extra_body():
    from pydantic import BaseModel
    from backend.providers.doubao_provider import DoubaoProvider

    class _Tiny(BaseModel):
        name: str

    class _FakeMsg:
        content = '{"name": "ok"}'
        reasoning_content = ""

    class _FakeChoice:
        finish_reason = "stop"
        message = _FakeMsg()

    class _FakeUsage:
        prompt_tokens = 10
        completion_tokens = 5
        total_tokens = 15
        completion_tokens_details = None

    class _FakeResp:
        choices = [_FakeChoice()]
        usage = _FakeUsage()

    class _FakeCompletions:
        def __init__(self):
            self.calls = []

        def create(self, **kwargs):
            self.calls.append(kwargs)
            return _FakeResp()

    class _FakeChat:
        def __init__(self):
            self.completions = _FakeCompletions()

    class _FakeClient:
        def __init__(self):
            self.chat = _FakeChat()

    p = object.__new__(DoubaoProvider)
    p.models = ["m1"]
    p.model = "m1"
    p.max_tokens = 8192
    p.no_thinking = True
    p._thinking_mode = "probe"
    p.last_usage = None
    p.client = _FakeClient()

    result = p._call_json("sys", "user", _Tiny, max_retries=0)
    assert result.name == "ok"

    call = p.client.chat.completions.calls[0]
    assert call["extra_body"] == {"thinking": {"type": "disabled"}}
    assert call["response_format"] == {"type": "json_object"}
    assert call["max_tokens"] == 8192
    assert p.last_usage["reasoning_tokens"] == 0
    assert p._thinking_mode == "thinking_disabled"

    # With thinking reduction off, no extra_body is attached.
    p.no_thinking = False
    p._thinking_mode = None
    p._call_json("sys", "user", _Tiny, max_retries=0)
    assert "extra_body" not in p.client.chat.completions.calls[-1]


def test_thinking_probe_falls_back_to_reasoning_low():
    from pydantic import BaseModel
    from backend.providers.doubao_provider import DoubaoProvider

    class _Tiny(BaseModel):
        name: str

    class _FakeMsg:
        content = '{"name": "ok"}'
        reasoning_content = ""

    class _FakeChoice:
        finish_reason = "stop"
        message = _FakeMsg()

    class _FakeUsage:
        prompt_tokens = 10
        completion_tokens = 5
        total_tokens = 15
        completion_tokens_details = None

    class _FakeResp:
        choices = [_FakeChoice()]
        usage = _FakeUsage()

    class _RejectingCompletions:
        """Simulates the observed GLM-style model: rejects thinking=disabled
        and reasoning_effort=minimal, accepts reasoning_effort=low."""

        def __init__(self):
            self.calls = []

        def create(self, **kwargs):
            self.calls.append(kwargs)
            extra = kwargs.get("extra_body") or {}
            if "thinking" in extra:
                raise Exception(
                    "Error code: 400 - InvalidParameter: thinking.type `disabled` "
                    "is not supported by this model")
            if extra.get("reasoning_effort") == "minimal":
                raise Exception(
                    "Error code: 400 - InvalidParameter: reasoning_effort `none` "
                    "is not supported by this model")
            return _FakeResp()

    class _FakeChat:
        def __init__(self):
            self.completions = _RejectingCompletions()

    class _FakeClient:
        def __init__(self):
            self.chat = _FakeChat()

    p = object.__new__(DoubaoProvider)
    p.models = ["m1"]
    p.model = "m1"
    p.max_tokens = 8192
    p.no_thinking = True
    p._thinking_mode = "probe"
    p.last_usage = None
    p.client = _FakeClient()

    result = p._call_json("sys", "user", _Tiny, max_retries=0)
    assert result.name == "ok"
    assert p._thinking_mode == "reasoning_low"

    # Second call uses the cached mode directly (no re-probe).
    p._call_json("sys", "user", _Tiny, max_retries=0)
    assert p.client.chat.completions.calls[-1]["extra_body"] == {"reasoning_effort": "low"}
