"""Задачи веб-интерфейса: состояние на диске и очередь с одним исполнителем.

Один исполнитель — намеренно: распознавание и разметка спикеров занимают видеокарту (8 ГБ),
а рендер — все ядра процессора. Параллельные задачи только мешали бы друг другу.
Состояние каждой задачи лежит в jobs/<id>/state.json и переживает перезапуск сервера.
"""

import json
import queue
import re
import threading
import time
import traceback
import uuid
from datetime import datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from chessify.paths import JOBS_DIR, ROOT
from chessify.schema import Scene

OUT_DIR = ROOT / "out"
Status = Literal["queued", "processing", "choose", "review", "rendering", "done", "error"]
ACTIVE: set[str] = {"queued", "processing", "rendering"}


class JobParams(BaseModel):
    mode: Literal["clip", "episode"] = Field(default="clip", description="episode — целая серия, сцену ищет модель")
    series: str
    hint: str = ""
    start: float | None = None
    end: float | None = None
    speakers: int | None = None
    profile: str | None = None
    length: str = "full"
    preset: str = "final"
    review: bool = Field(default=True, description="Остановиться после анализа, чтобы поправить ходы")
    music: str | None = Field(default=None, description="Трек из библиотеки музыки")
    music_volume: float = Field(default=0.12, ge=0, le=1)


class JobState(BaseModel):
    id: str
    created: str
    source: str  # имя загруженного файла
    params: JobParams
    status: Status = "queued"
    step: str = "в очереди"
    progress: float | None = None
    log: list[str] = []
    error: str | None = None
    outputs: list[str] = []  # имена готовых роликов в out/


def _slug(name: str) -> str:
    base = re.sub(r"[^\w-]+", "-", Path(name).stem, flags=re.UNICODE).strip("-").lower()[:40] or "scene"
    return f"{datetime.now():%Y%m%d-%H%M%S}-{base}-{uuid.uuid4().hex[:4]}"


class JobStore:
    def __init__(self, root: Path = JOBS_DIR) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def path(self, job_id: str) -> Path:
        if not re.fullmatch(r"[\w-]+", job_id):
            raise KeyError(job_id)
        return self.root / job_id

    def create(self, filename: str, params: JobParams) -> JobState:
        job_id = _slug(filename)
        self.path(job_id).mkdir(parents=True)
        ext = Path(filename).suffix.lower() or ".mp4"
        state = JobState(id=job_id, created=datetime.now().isoformat(timespec="seconds"), source=f"source{ext}",
                         params=params)
        self.save(state)
        return state

    def get(self, job_id: str) -> JobState:
        f = self.path(job_id) / "state.json"
        if not f.exists():
            raise KeyError(job_id)
        return JobState.model_validate_json(f.read_text(encoding="utf-8"))

    def save(self, state: JobState) -> None:
        with self._lock:
            f = self.path(state.id) / "state.json"
            tmp = f.with_suffix(".tmp")
            tmp.write_text(state.model_dump_json(indent=1), encoding="utf-8")
            tmp.replace(f)

    def update(self, job_id: str, **changes) -> JobState:
        state = self.get(job_id).model_copy(update=changes)
        self.save(state)
        return state

    def append_log(self, job_id: str, line: str) -> None:
        state = self.get(job_id)
        state.log = (state.log + [f"{datetime.now():%H:%M:%S} {line}"])[-200:]
        self.save(state)

    def all(self) -> list[JobState]:
        states = []
        for d in self.root.iterdir():
            if (d / "state.json").exists():
                try:
                    states.append(self.get(d.name))
                except Exception:  # noqa: BLE001 — битая задача не должна ломать список
                    continue
        return sorted(states, key=lambda s: s.created, reverse=True)

    def candidates(self, job_id: str) -> list[dict]:
        f = self.path(job_id) / "candidates.json"
        return json.loads(f.read_text(encoding="utf-8")) if f.exists() else []

    def scene_path(self, job_id: str) -> Path:
        return self.path(job_id) / "scene.json"

    def load_scene(self, job_id: str) -> Scene:
        return Scene.model_validate_json(self.scene_path(job_id).read_text(encoding="utf-8"))

    def recover(self) -> None:
        """После перезапуска сервера незавершённые задачи помечаются ошибкой — их можно запустить заново."""
        for s in self.all():
            if s.status in ACTIVE:
                self.update(s.id, status="error", error="сервер был перезапущен во время обработки", progress=None)


Task = tuple[Literal["process", "render"], str]


class Worker:
    """Очередь задач с одним исполнителем в отдельном потоке."""

    def __init__(self, store: JobStore) -> None:
        self.store = store
        self.queue: queue.Queue[Task] = queue.Queue()
        self.thread = threading.Thread(target=self._loop, daemon=True, name="chessify-worker")

    def start(self) -> None:
        self.thread.start()

    def submit(self, kind: Literal["process", "render"], job_id: str) -> None:
        self.store.update(job_id, status="queued", step="в очереди", error=None, progress=None)
        self.queue.put((kind, job_id))

    def _loop(self) -> None:
        while True:
            kind, job_id = self.queue.get()
            try:
                self._process(job_id) if kind == "process" else self._render(job_id)
            except Exception as e:  # noqa: BLE001 — ошибка задачи показывается пользователю, сервер живёт
                self.store.append_log(job_id, traceback.format_exc(limit=3))
                self.store.update(job_id, status="error", error=str(e) or e.__class__.__name__, progress=None)
            finally:
                self.queue.task_done()

    def _log(self, job_id: str):
        def log(line: str) -> None:
            self.store.append_log(job_id, line)
            if re.match(r"\d/5 ", line):
                self.store.update(job_id, step=line.split(":")[0])
        return log

    def _process(self, job_id: str) -> None:
        from chessify import settings
        from chessify.config import load_config
        from chessify.pipeline import Job

        state = self.store.update(job_id, status="processing", step="подготовка")
        p = state.params
        cfg = load_config()
        roles = cfg.profile(p.profile)
        if missing := [k for k in cfg.missing_keys(roles) if k != "HF_TOKEN"]:
            raise RuntimeError(f"Профилю «{cfg.resolve(p.profile)}» не хватает ключей: {settings.describe(missing)}. "
                               "Впишите их в «Настройках» или выберите другую в поле «Модель для разбора».")
        job = Job(job_id, log=self._log(job_id))
        source = self.store.path(job_id) / state.source
        if p.mode == "episode" and p.start is None and p.end is None:
            candidates = job.find_scenes(source, cfg, roles, p.series, p.hint)
            if not candidates:
                raise RuntimeError("в серии не нашлось подходящих сцен-дуэлей; задайте начало и конец вручную")
            if p.review:
                self.store.update(job_id, status="choose", step="выберите сцену", progress=None)
                return
            p = p.model_copy(update={"start": candidates[0].start, "end": candidates[0].end})
            self.store.update(job_id, params=p)
            self._log(job_id)(f"   взята сцена «{candidates[0].title}» ({candidates[0].start:.0f}–{candidates[0].end:.0f} с)")
        job.process(source, cfg, roles, p.series, p.hint, p.start, p.end, p.speakers)
        if p.review:
            self.store.update(job_id, status="review", step="проверьте ходы и запустите рендер", progress=None)
        else:
            self._render(job_id)

    def _render(self, job_id: str) -> None:
        from chessify.pipeline import add_music, render_scene

        state = self.store.update(job_id, status="rendering", step="5/5 рендер", progress=0.0)
        p = state.params
        name = f"{job_id}_{p.length}_{p.preset}.mp4"
        last = [0.0]

        def progress(x: float) -> None:
            if x - last[0] >= 0.02 or x >= 1:  # не пишем state.json на каждый кадр
                last[0] = x
                self.store.update(job_id, progress=round(x, 3))

        scene = add_music(self.store.load_scene(job_id), p.music, p.music_volume)
        render_scene(scene, OUT_DIR / name, p.preset, p.length, log=self._log(job_id), progress=progress)
        outputs = [o for o in self.store.get(job_id).outputs if o != name] + [name]
        self.store.update(job_id, status="done", step="готово", progress=None, outputs=outputs)


def wait_idle(worker: Worker, timeout: float = 30) -> None:
    """Для тестов: дождаться, пока очередь опустеет."""
    end = time.time() + timeout
    while worker.queue.unfinished_tasks and time.time() < end:
        time.sleep(0.05)


def dump(state: JobState) -> dict:
    return json.loads(state.model_dump_json())
