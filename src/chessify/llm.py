"""Сменяемые LLM-провайдеры.

Конвейер вызывает только `complete_json(role, ...)`: какая модель и чей SDK стоят за ролью,
решает config/providers.yaml. Ответ всегда проверяется Pydantic-моделью; при ошибке модели
возвращается текст ошибки, и она получает до `retries` попыток исправиться.
"""

import base64
import json
import os
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol, TypeVar

from pydantic import BaseModel, ValidationError

from chessify.config import Config, ModelCfg, ProviderCfg
from chessify.i18n import pick

T = TypeVar("T", bound=BaseModel)


@dataclass
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0


@dataclass
class LLMResult:
    text: str
    usage: Usage = field(default_factory=Usage)


class LLMClient(Protocol):
    def complete(self, system: str, user: str, schema: dict | None, images: list[Path]) -> LLMResult: ...


def _image_data_url(path: Path) -> str:
    mime = "image/png" if path.suffix.lower() == ".png" else "image/jpeg"
    return f"data:{mime};base64,{base64.b64encode(path.read_bytes()).decode()}"


def _schema_hint(schema: dict) -> str:
    return "Ответь одним JSON-объектом строго по этой JSON Schema, без пояснений:\n" + json.dumps(
        schema, ensure_ascii=False
    )


class OpenAICompatClient:
    """OpenAI и всё, что говорит на его API: DeepSeek, Gemini, OpenRouter, свои серверы (vLLM, Ollama, LM Studio)."""

    def __init__(self, provider: ProviderCfg, model: ModelCfg) -> None:
        from openai import OpenAI

        key = os.environ.get(provider.key_env, "") if provider.key_env else "local"
        if provider.key_env and not key:
            raise RuntimeError(f"не задан {provider.key_env}: впишите в «Настройках» веб-интерфейса или в .env")
        # Бесплатные тарифы (Gemini, OpenRouter) быстро отвечают 429: SDK ждёт и повторяет сам.
        self.client = OpenAI(api_key=key, base_url=provider.base_url, max_retries=6)
        self.model = model

    def complete(self, system: str, user: str, schema: dict | None, images: list[Path]) -> LLMResult:
        content: list[dict] | str = user
        if images:
            content = [{"type": "text", "text": user}] + [
                {"type": "image_url", "image_url": {"url": _image_data_url(p)}} for p in images
            ]
        kwargs: dict = {}
        if schema is not None:
            if "json_schema" in self.model.caps:
                kwargs["response_format"] = {
                    "type": "json_schema",
                    "json_schema": {"name": "result", "schema": schema, "strict": False},
                }
            else:
                kwargs["response_format"] = {"type": "json_object"}
                system = f"{system}\n\n{_schema_hint(schema)}"
        messages = [{"role": "system", "content": system}, {"role": "user", "content": content}]
        try:
            resp = self.client.chat.completions.create(model=self.model.id, messages=messages, **kwargs)
        except Exception as e:  # noqa: BLE001
            from openai import BadRequestError

            # Самостоятельно развёрнутые серверы (старый vLLM, Ollama и др.) не всегда понимают response_format.
            # Тогда просим JSON текстом: ответ всё равно проверяется схемой в LLMRouter.
            if not (isinstance(e, BadRequestError) and "response_format" in kwargs):
                raise
            kwargs.pop("response_format")
            if schema is not None and "json_schema" in self.model.caps:
                messages[0]["content"] = f"{system}\n\n{_schema_hint(schema)}"
            resp = self.client.chat.completions.create(model=self.model.id, messages=messages, **kwargs)
        u = resp.usage
        usage = Usage(u.prompt_tokens, u.completion_tokens) if u else Usage()
        return LLMResult(resp.choices[0].message.content or "", usage)


class AnthropicClient:
    def __init__(self, provider: ProviderCfg, model: ModelCfg) -> None:
        import anthropic

        key = os.environ.get(provider.key_env or "", "")
        if not key:
            raise RuntimeError(f"не задан {provider.key_env}: впишите в «Настройках» веб-интерфейса или в .env")
        self.client = anthropic.Anthropic(api_key=key)
        self.model = model

    def complete(self, system: str, user: str, schema: dict | None, images: list[Path]) -> LLMResult:
        blocks: list[dict] = [
            {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": "image/png" if p.suffix.lower() == ".png" else "image/jpeg",
                    "data": base64.b64encode(p.read_bytes()).decode(),
                },
            }
            for p in images
        ]
        blocks.append({"type": "text", "text": user})
        output_config: dict = {"effort": "high"}  # у Opus 5.5 по умолчанию medium
        if schema is not None:
            output_config["format"] = {"type": "json_schema", "schema": schema}
        # Серверный запасной вариант при отказе модели: маршрут выбирается API по категории отказа.
        resp = self.client.beta.messages.create(
            model=self.model.id,
            max_tokens=16000,
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
            output_config=output_config,
            system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
            messages=[{"role": "user", "content": blocks}],
        )
        if resp.stop_reason == "refusal":
            raise RuntimeError(f"модель отказалась отвечать: {resp.stop_details}")
        text = "".join(b.text for b in resp.content if b.type == "text")
        return LLMResult(text, Usage(resp.usage.input_tokens, resp.usage.output_tokens))


class ClaudeCodeClient:
    """Claude по подписке Claude Code: `claude -p` в чистом режиме, без инструментов, ответ по JSON-схеме."""

    def __init__(self, provider: ProviderCfg, model: ModelCfg) -> None:
        exe = shutil.which("claude")
        if not exe:
            raise RuntimeError("CLI claude не найден в PATH")
        self.exe = exe
        self.model = model

    def complete(self, system: str, user: str, schema: dict | None, images: list[Path]) -> LLMResult:
        prompt = user
        tools = ""
        if images:
            # Изображения claude -p читает инструментом Read по путям.
            prompt += "\n\nКадры (прочитай каждый файл перед ответом):\n" + "\n".join(str(p.resolve()) for p in images)
            tools = "Read"
        args = [self.exe, "-p", "--output-format", "json", "--model", self.model.id,
                "--system-prompt", system, "--tools", tools, "--permission-mode", "dontAsk",
                "--no-session-persistence"]
        if images:
            args += ["--allowedTools", "Read"]
        if schema is not None:
            args += ["--json-schema", json.dumps(schema, ensure_ascii=False)]
        proc = subprocess.run(args, input=prompt, capture_output=True, text=True, encoding="utf-8", timeout=900)
        if proc.returncode != 0:
            raise RuntimeError(f"claude -p завершился с кодом {proc.returncode}: {proc.stdout[-500:]} {proc.stderr[-500:]}")
        out = json.loads(proc.stdout)
        if out.get("is_error"):
            raise RuntimeError(f"claude -p: {out.get('result')}")
        text = json.dumps(out["structured_output"], ensure_ascii=False) if "structured_output" in out else out["result"]
        u = out.get("usage") or {}
        return LLMResult(text, Usage(u.get("input_tokens", 0), u.get("output_tokens", 0), out.get("total_cost_usd", 0.0)))


ADAPTERS = {"openai_compat": OpenAICompatClient, "anthropic": AnthropicClient, "claude_code": ClaudeCodeClient}


def _extract_json(text: str) -> str:
    """Некоторые модели оборачивают JSON в ```json …``` даже в JSON-режиме."""
    t = text.strip()
    if t.startswith("```"):
        t = t.split("\n", 1)[1] if "\n" in t else t
        t = t.rsplit("```", 1)[0]
    start, end = t.find("{"), t.rfind("}")
    return t[start : end + 1] if start != -1 and end != -1 else t


class LLMRouter:
    """Роль → модель по профилю; учёт расходов по всем вызовам."""

    def __init__(self, config: Config, roles: dict[str, str]) -> None:
        self.config = config
        self.roles = roles
        self.total = Usage()
        self._clients: dict[str, LLMClient] = {}

    def client_for(self, role: str) -> tuple[LLMClient, ModelCfg]:
        model_name = self.roles[role]
        model = self.config.models[model_name]
        if model_name not in self._clients:
            provider = self.config.providers[model.provider]
            self._clients[model_name] = ADAPTERS[provider.adapter](provider, model)
        return self._clients[model_name], model

    def complete_json(self, role: str, system: str, user: str, result_type: type[T],
                      images: list[Path] | None = None, retries: int = 2) -> T:
        client, model = self.client_for(role)
        if images and "vision" not in model.caps:
            raise ValueError(f"модель роли {role} не принимает изображения")
        schema = result_type.model_json_schema()
        prompt = user
        last_error = ""
        for _ in range(retries + 1):
            res = client.complete(system, prompt, schema, images or [])
            self._account(model, res.usage)
            try:
                return result_type.model_validate_json(_extract_json(res.text))
            except ValidationError as e:
                last_error = str(e)
                prompt = (f"{user}\n\nПредыдущий ответ не прошёл проверку схемы:\n{last_error[:2000]}\n"
                          "Исправь и верни только корректный JSON.")
        raise RuntimeError(f"роль {role}: модель не вернула валидный JSON за {retries + 1} попыток: {last_error[:500]}")

    def _account(self, model: ModelCfg, u: Usage) -> None:
        cost = u.cost_usd
        if not cost and model.price_per_mtok:
            cost = (u.input_tokens * model.price_per_mtok[0] + u.output_tokens * model.price_per_mtok[1]) / 1e6
        self.total.input_tokens += u.input_tokens
        self.total.output_tokens += u.output_tokens
        self.total.cost_usd += cost


def check_provider(cfg: Config, provider: str, model: str | None = None) -> dict:
    """Проверка подключения: список моделей на сервере (для OpenAI-совместимых) и пробный ответ в JSON.

    Возвращает {"ok", "lines", "models"} — для `chessify llm-check` и кнопки «Проверить» в вебе.
    """
    prov = cfg.providers[provider]
    lines = [pick("Провайдер", "Provider") + f" {provider}: {prov.adapter}, {prov.base_url or '—'}"]
    models: list[str] = []
    if prov.adapter == "openai_compat":
        from openai import OpenAI

        key = os.environ.get(prov.key_env or "", "") or "none"
        try:
            models = [m.id for m in OpenAI(api_key=key, base_url=prov.base_url, timeout=20).models.list()]
            more = len(models) - 15
            shown = ", ".join(models[:15]) + (pick(f" … и ещё {more}", f" … and {more} more") if more > 0 else "")
            lines.append(pick("Модели на сервере: ", "Models on the server: ") + (shown or "—"))
        except Exception as e:  # noqa: BLE001
            lines.append(pick("Список моделей недоступен: ", "Model list unavailable: ") + str(e))
    name = model or next((n for n, m in cfg.models.items() if m.provider == provider), None)
    if not name:
        lines.append(pick(f"в config/providers.yaml нет моделей провайдера {provider}",
                          f"config/providers.yaml has no models for provider {provider}"))
        return {"ok": False, "lines": lines, "models": models}
    lines.append(pick("Пробный запрос к модели", "Test request to model") + f" {name} ({cfg.models[name].id})…")

    class Probe(BaseModel):
        category: str
        title: str

    router = LLMRouter(cfg, {"grade": name})
    try:
        out = router.complete_json("grade", "Ты шахматный комментатор. Отвечай по-русски.",
                                   "Ход: «Верно.» в ответ на вопрос об отказе от адвоката. Дай category и title.", Probe)
    except Exception as e:  # noqa: BLE001
        lines.append(pick("Ошибка: ", "Error: ") + f"{e.__class__.__name__}: {e}")
        lines.append(pick("Проверьте адрес (обычно заканчивается на /v1), ключ, имя модели и доступ к сети (VPN).",
                          "Check the address (usually ends with /v1), the key, the model name and network access (VPN).")
                     if provider == "custom" else
                     pick("Проверьте ключ, имя модели и доступ к сети (VPN).",
                          "Check the key, the model name and network access (VPN)."))
        return {"ok": False, "lines": lines, "models": models}
    lines.append(f"OK: {out.model_dump()}; " + pick("токены", "tokens")
                 + f" {router.total.input_tokens}/{router.total.output_tokens}")
    return {"ok": True, "lines": lines, "models": models}
