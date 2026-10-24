"""Конфиг провайдеров: какие модели выполняют какие роли."""

import os
import re
from pathlib import Path
from typing import Literal

import yaml
from dotenv import load_dotenv
from pydantic import BaseModel

from chessify import settings
from chessify.paths import ROOT

CONFIG_PATH = ROOT / "config" / "providers.yaml"

Cap = Literal["json_schema", "json_object", "vision", "video"]
LLM_ROLES = ("scene_select", "segment", "grade", "edit", "nonverbal")


class ProviderCfg(BaseModel):
    adapter: Literal["openai_compat", "anthropic", "claude_code"]
    base_url: str | None = None
    key_env: str | None = None


class ModelCfg(BaseModel):
    provider: str
    id: str
    caps: list[Cap] = []
    price_per_mtok: tuple[float, float] | None = None  # вход, выход; $ за 1M токенов


class AsrCfg(BaseModel):
    adapter: Literal["faster_whisper"]
    model: str
    device: str = "auto"
    compute_type: str = "default"


class DiarCfg(BaseModel):
    adapter: Literal["pyannote"]
    model: str
    device: str = "auto"
    token_env: str | None = None


class Config(BaseModel):
    providers: dict[str, ProviderCfg]
    models: dict[str, ModelCfg]
    asr: dict[str, AsrCfg]
    diarization: dict[str, DiarCfg]
    profiles: dict[str, dict[str, str]]
    default_profile: str
    profile_aliases: dict[str, str] = {}  # старые имена профилей → новые

    def resolve(self, name: str | None) -> str:
        name = name or self.default_profile
        return name if name in self.profiles else self.profile_aliases.get(name, name)

    def profile(self, name: str | None, overrides: dict[str, str] | None = None) -> dict[str, str]:
        name = self.resolve(name)
        if name not in self.profiles:
            raise KeyError(f"нет профиля {name!r}; есть: {', '.join(self.profiles)}")
        roles = {**self.profiles[name], **(overrides or {})}
        for role in LLM_ROLES:
            if role in roles and roles[role] not in self.models:
                raise KeyError(f"роль {role}: нет модели {roles[role]!r}")
        return roles

    def missing_keys(self, roles: dict[str, str]) -> list[str]:
        """Переменные окружения, которых не хватает для выбранного профиля."""
        need: set[str] = set()
        for role in LLM_ROLES:
            if role in roles:
                env = self.providers[self.models[roles[role]].provider].key_env
                if env:
                    need.add(env)
        if "diarization" in roles and (env := self.diarization[roles["diarization"]].token_env):
            need.add(env)
        return sorted(e for e in need if not os.environ.get(e))


def _expand_env(text: str) -> str:
    """${VAR} и ${VAR:-по умолчанию} в конфиге — адрес и имя модели можно держать в .env."""
    return re.sub(r"\$\{(\w+)(?::-([^}]*))?\}", lambda m: os.environ.get(m.group(1)) or (m.group(2) or ""), text)


def load_config(path: Path = CONFIG_PATH) -> Config:
    load_dotenv(ROOT / ".env")
    settings.apply()
    cfg = Config.model_validate(yaml.safe_load(_expand_env(path.read_text(encoding="utf-8"))))
    if (default := cfg.resolve(os.environ.get("CHESSIFY_DEFAULT_PROFILE"))) in cfg.profiles:
        cfg.default_profile = default  # выбран в настройках веб-интерфейса
    return cfg
