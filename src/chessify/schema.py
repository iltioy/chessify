"""Единая схема данных сцены.

Источник правды для всех частей проекта: из этих моделей экспортируется JSON Schema
(для запросов к LLM и валидации) и TypeScript-типы для шаблона Remotion.
"""

from enum import StrEnum

from pydantic import BaseModel, Field


class Category(StrEnum):
    brilliant = "brilliant"
    best = "best"
    excellent = "excellent"
    good = "good"
    inaccuracy = "inaccuracy"
    mistake = "mistake"
    blunder = "blunder"


class Side(StrEnum):
    white = "white"
    black = "black"


class Word(BaseModel):
    t0: float = Field(description="Начало слова, секунды исходного клипа")
    t1: float = Field(description="Конец слова, секунды исходного клипа")
    w: str = Field(description="Слово с пунктуацией, как в субтитрах")
    spk: str | None = Field(default=None, description="Метка спикера из распознавания")


class Player(BaseModel):
    name: str
    speakers: list[str] = Field(default_factory=list, description="Метки спикеров этой стороны")
    avatar: str | None = Field(default=None, description="Путь к аватару относительно папки ассетов")


class Players(BaseModel):
    white: Player
    black: Player


class Move(BaseModel):
    n: int = Field(ge=1, description="Номер хода; белые и чёрные делят номер, как в шахматной нотации")
    side: Side
    t0: float = Field(description="Начало реплики, секунды исходного клипа")
    t1: float = Field(description="Конец реплики; после него кадр замирает и показывается карточка")
    quote: str
    category: Category
    title: str = Field(max_length=40, description="Название хода, 1–4 слова")
    comment: str = Field(max_length=220, description="1–2 предложения анализа")
    eval_after: float = Field(description="Оценка позиции после хода; плюс — преимущество белых")
    mate_in: int | None = Field(
        default=None, ge=0, description="Мат через N ходов фаворита (0 — мат на доске); только в концовке партии")
    show_card: bool = True
    nonverbal: bool = False


class Summary(BaseModel):
    verdict: str = Field(description="Крупная строка итога, например «МАТА НЕТ»")
    line: str = Field(description="Одна строка вывода под вердиктом")


class Meta(BaseModel):
    series: str
    title: str = Field(description="Заголовок ролика; перенос строки через \\n")
    kicker: str = Field(default="Разбор сцены", description="Надзаголовок перед названием сериала")
    watermark: str | None = None
    clip: str = Field(description="Видео сцены относительно папки ассетов")
    background: str | None = Field(default=None, description="Заранее размытый фон; если нет — размывается в шаблоне")
    eval_start: float = Field(default=0.0, description="Оценка до первого хода")
    music: str | None = Field(default=None, description="Фоновая музыка относительно папки ассетов")
    music_volume: float = Field(default=0.12, ge=0, le=1, description="Громкость музыки под речью; на карточках — вдвое громче")
    excerpts: list[tuple[float, float]] | None = Field(
        default=None, description="Короткая версия: проигрывать только эти отрезки исходника [начало, конец]"
    )


class Scene(BaseModel):
    meta: Meta
    players: Players
    words: list[Word]
    moves: list[Move]
    summary: Summary
