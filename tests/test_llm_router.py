from pathlib import Path

import pytest
from pydantic import BaseModel

from chessify.config import load_config
from chessify.llm import LLMResult, LLMRouter, Usage, _extract_json


class Verdict(BaseModel):
    category: str
    title: str


class FakeClient:
    """Записанные ответы вместо сети: проверяем логику роутера без ключей."""

    def __init__(self, replies: list[str]) -> None:
        self.replies = replies
        self.prompts: list[str] = []

    def complete(self, system: str, user: str, schema: dict | None, images: list[Path]) -> LLMResult:
        self.prompts.append(user)
        return LLMResult(self.replies.pop(0), Usage(1000, 500))


def router_with(replies: list[str], profile: str = "deepseek") -> tuple[LLMRouter, FakeClient]:
    cfg = load_config()
    router = LLMRouter(cfg, cfg.profile(profile))
    fake = FakeClient(replies)
    router._clients[router.roles["grade"]] = fake
    return router, fake


def test_valid_json_first_try() -> None:
    router, _ = router_with(['{"category": "good", "title": "Рассадка"}'])
    assert router.complete_json("grade", "s", "u", Verdict).title == "Рассадка"
    # deepseek-pro: $1.32 / $3.96 за 1M → 1000 и 500 токенов = 0.00330
    assert router.total.cost_usd == pytest.approx(0.0033)


def test_retry_after_invalid_json_includes_error() -> None:
    router, fake = router_with(['{"category": "good"}', '```json\n{"category": "best", "title": "Запись"}\n```'])
    assert router.complete_json("grade", "s", "u", Verdict).category == "best"
    assert "не прошёл проверку схемы" in fake.prompts[1]


def test_gives_up_after_retries() -> None:
    router, _ = router_with(["{}", "{}", "{}"])
    with pytest.raises(RuntimeError, match="валидный JSON"):
        router.complete_json("grade", "s", "u", Verdict, retries=2)


def test_profile_override_and_missing_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = load_config()
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("HF_TOKEN", raising=False)
    roles = cfg.profile("openai", {"grade": "claude"})
    assert roles["grade"] == "claude"
    assert cfg.missing_keys(roles) == ["HF_TOKEN", "OPENAI_API_KEY"]


def test_old_profile_names_still_work() -> None:
    cfg = load_config()
    assert cfg.profile("work") == cfg.profile("custom")  # задачи и настройки прошлых версий
    assert cfg.profile("dev") == cfg.profile("claude")
    assert cfg.profile("cheap") == cfg.profile("custom")  # облачный Qwen убран


def test_extract_json_strips_fences() -> None:
    assert _extract_json('Вот ответ:\n```json\n{"a": 1}\n```') == '{"a": 1}'


def test_gemini_profile_needs_only_gemini_key(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in ("GEMINI_API_KEY", "GEMINI_MODEL", "HF_TOKEN"):
        monkeypatch.delenv(key, raising=False)
    cfg = load_config()
    roles = cfg.profile("gemini")
    assert cfg.missing_keys(roles) == ["GEMINI_API_KEY", "HF_TOKEN"]
    assert cfg.models[roles["grade"]].id == "gemini-3.8-flash"
    monkeypatch.setenv("GEMINI_MODEL", "gemini-3.6-flash")  # имя модели меняется в «Настройках»
    assert load_config().models["gemini-flash"].id == "gemini-3.6-flash"


def test_deepseek_profile(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in ("DEEPSEEK_API_KEY", "HF_TOKEN"):
        monkeypatch.delenv(key, raising=False)
    cfg = load_config()
    roles = cfg.profile("deepseek")
    assert cfg.missing_keys(roles) == ["DEEPSEEK_API_KEY", "HF_TOKEN"]
    assert cfg.models[roles["grade"]].id == "deepseek-v4-pro" and cfg.models[roles["segment"]].id == "deepseek-flash"
