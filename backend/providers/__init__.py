from .base import LLMProvider

__all__ = ["LLMProvider", "DoubaoProvider", "DeepSeekProvider"]


def __getattr__(name: str):
    if name == "DoubaoProvider":
        from .doubao_provider import DoubaoProvider

        return DoubaoProvider
    if name == "DeepSeekProvider":
        from .deepseek_provider import DeepSeekProvider

        return DeepSeekProvider
    raise AttributeError(name)
