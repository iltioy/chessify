"""FastAPI: REST API задач + одна статическая страница интерфейса."""

import os
import shutil
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ValidationError

from chessify import i18n, settings
from chessify.i18n import pick
from chessify.condense import PRESETS
from chessify.config import load_config
from chessify.paths import MUSIC_DIR, MUSIC_EXT
from chessify.schema import Scene
from chessify.scoring import WEIGHTS
from chessify.web.jobs import OUT_DIR, JobParams, JobState, JobStore, Worker

STATIC = Path(__file__).parent / "static"
LENGTHS = {"full": ("Вся сцена", "Whole scene"), "short3": ("До 3 минут", "Up to 3 minutes"),
           "reels": ("До 90 секунд", "Up to 90 seconds"), "shorts": ("До 60 секунд", "Up to 60 seconds")}
PRESETS_UI = {"final": ("1080×1920", "1080×1920"), "draft": ("720×1280 (быстрее)", "720×1280 (faster)")}
VIDEO_EXT = {".mp4", ".mkv", ".mov", ".avi", ".webm", ".m4v"}

store = JobStore()
worker = Worker(store)


@asynccontextmanager
async def lifespan(_: FastAPI):
    store.recover()
    worker.start()
    yield


app = FastAPI(title="Chessify", lifespan=lifespan)


@app.middleware("http")
async def ui_language(request: Request, call_next):
    """Язык интерфейса — из заголовка X-Lang (его шлёт страница): на нём ответы и ошибки."""
    token = i18n.current.set(i18n.norm(request.headers.get("x-lang")))
    try:
        return await call_next(request)
    finally:
        i18n.current.reset(token)


def _job(job_id: str) -> JobState:
    try:
        return store.get(job_id)
    except KeyError:
        raise HTTPException(404, pick("задача не найдена", "job not found")) from None


@app.get("/api/config")
def get_config() -> dict:
    cfg = load_config()
    profiles = {}
    for name in cfg.profiles:
        roles = cfg.profile(name)
        missing = cfg.missing_keys(roles)
        profiles[name] = {"label": settings.tr(TITLES[name]) if name in TITLES else name, "missing_keys": missing,
                          "missing_labels": [settings.describe([k]) for k in missing]}
    return {"profiles": profiles, "default_profile": cfg.default_profile,
            "lengths": {k: pick(*v) for k, v in LENGTHS.items()}, "presets": {k: pick(*v) for k, v in PRESETS_UI.items()},
            "weights": {c.value: w for c, w in WEIGHTS.items()}}


TITLES = {s.id: s.title for s in settings.SECTIONS if s.kind == "llm"}


def _ready(cfg, section_id: str) -> bool | None:
    """Раздел настроен: ключи на месте. None — проверить нельзя (вход в Claude Code — из терминала)."""
    if section_id == "hf":
        return bool(os.environ.get("HF_TOKEN"))
    if section_id == "claude":
        return None
    missing = [k for k in cfg.missing_keys(cfg.profile(section_id)) if k != "HF_TOKEN"]
    return not missing and (section_id != "custom" or bool(os.environ.get("CUSTOM_LLM_BASE_URL")))


@app.get("/api/settings")
def get_settings() -> dict:
    """Ключи и подключения по разделам. Секреты отдаются только маской."""
    cfg = load_config()
    sections = [{**sec, "ready": _ready(cfg, sec["id"])} for sec in settings.status(lang=i18n.current.get())]
    return {"sections": sections, "default_profile": cfg.default_profile}


class SettingsUpdate(BaseModel):
    values: dict[str, str] = {}  # пустая строка — не менять
    clear: list[str] = []


@app.put("/api/settings")
def put_settings(req: SettingsUpdate) -> dict:
    cfg = load_config()
    profile = req.values.get(settings.DEFAULT_PROFILE_KEY)
    if profile and profile not in cfg.profiles:
        raise HTTPException(400, pick(f"нет профиля {profile}", f"no profile {profile}"))
    try:
        settings.save(req.values, req.clear)
    except ValueError as e:
        raise HTTPException(400, str(e)) from None
    return get_settings()


class CheckRequest(BaseModel):
    target: str  # провайдер из config/providers.yaml или "hf"


@app.post("/api/settings/check")
def check_settings(req: CheckRequest) -> dict:
    """Проверка подключения уже сохранённых настроек: пробный запрос к LLM или доступ к модели pyannote."""
    cfg = load_config()
    try:
        if req.target == "hf":
            from chessify.diarization import check_hf_token

            d = next(iter(cfg.diarization.values()))
            return check_hf_token(d.model, os.environ.get(d.token_env or "", "") or None)
        if req.target not in cfg.providers:
            raise HTTPException(400, pick(f"нет провайдера {req.target}", f"no provider {req.target}"))
        from chessify.llm import check_provider

        return check_provider(cfg, req.target)
    except HTTPException:
        raise
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "lines": [f"{e.__class__.__name__}: {e}"], "models": []}


@app.get("/api/jobs")
def list_jobs() -> list[dict]:
    return [s.model_dump(exclude={"log"}) for s in store.all()]


@app.post("/api/jobs", status_code=201)
async def create_job(
    video: UploadFile = File(...),
    series: str = Form(...),
    hint: str = Form(""),
    start: float | None = Form(None),
    end: float | None = Form(None),
    speakers: int | None = Form(None),
    profile: str | None = Form(None),
    length: str = Form("full"),
    preset: str = Form("final"),
    # Строка, а не bool: FastAPI считает отсутствующее булево поле формы ложным, а умолчание здесь — «да».
    review: str = Form("true"),
    mode: str = Form("clip"),
    music: str | None = Form(None),
    music_volume: float = Form(0.12),
    language: str = Form(""),  # язык ролика; пусто — как язык интерфейса
) -> dict:
    if Path(video.filename or "").suffix.lower() not in VIDEO_EXT:
        raise HTTPException(400, pick("нужен видеофайл: ", "a video file is needed: ") + ", ".join(sorted(VIDEO_EXT)))
    if length not in LENGTHS or preset not in ("final", "draft"):
        raise HTTPException(400, pick("неизвестная длина или качество", "unknown length or quality"))
    if profile and profile not in load_config().profiles:
        raise HTTPException(400, pick(f"нет профиля {profile}", f"no profile {profile}"))
    if mode not in ("clip", "episode"):
        raise HTTPException(400, pick("режим: clip или episode", "mode: clip or episode"))
    _check_music(music)
    params = JobParams(mode=mode, series=series.strip(), hint=hint.strip(), start=start, end=end, speakers=speakers,
                       profile=profile or None, length=length, preset=preset,
                       review=review.strip().lower() not in ("false", "0", "off", "no"),
                       music=music or None, music_volume=music_volume,
                       language=i18n.norm(language or i18n.current.get()), ui_lang=i18n.norm(i18n.current.get()))
    state = store.create(video.filename or "scene.mp4", params)
    with (store.path(state.id) / state.source).open("wb") as f:
        shutil.copyfileobj(video.file, f, length=8 * 1024 * 1024)
    worker.submit("process", state.id)
    return store.get(state.id).model_dump()


@app.get("/api/jobs/{job_id}")
def get_job(job_id: str) -> dict:
    state = _job(job_id)
    return {**state.model_dump(), "has_scene": store.scene_path(job_id).exists()}


@app.get("/api/jobs/{job_id}/candidates")
def get_candidates(job_id: str) -> list[dict]:
    _job(job_id)
    return store.candidates(job_id)


class SceneChoice(BaseModel):
    index: int | None = None  # номер кандидата
    start: float | None = None  # или свои границы
    end: float | None = None


@app.post("/api/jobs/{job_id}/choose")
def choose(job_id: str, req: SceneChoice) -> dict:
    """Выбор сцены из кандидатов (или своих границ) — дальше обычная обработка выбранного отрезка."""
    state = _job(job_id)
    if state.status not in ("choose", "error"):
        raise HTTPException(409, pick("сцена выбирается после поиска кандидатов", "a scene is chosen after the candidates are found"))
    if req.index is not None:
        cands = store.candidates(job_id)
        if not 0 <= req.index < len(cands):
            raise HTTPException(400, pick("нет такого кандидата", "no such candidate"))
        start, end = cands[req.index]["start"], cands[req.index]["end"]
    elif req.start is not None and req.end is not None and req.end > req.start >= 0:
        start, end = req.start, req.end
    else:
        raise HTTPException(400, pick("укажите кандидата или начало и конец", "pick a candidate or set the start and end"))
    store.update(job_id, params=state.params.model_copy(update={"start": start, "end": end}))
    worker.submit("process", job_id)
    return store.get(job_id).model_dump()


@app.get("/api/jobs/{job_id}/source")
def source(job_id: str) -> FileResponse:
    """Исходное видео — для предпросмотра кандидатов сцен."""
    state = _job(job_id)
    return FileResponse(store.path(job_id) / state.source)


@app.get("/api/jobs/{job_id}/scene")
def get_scene(job_id: str) -> dict:
    _job(job_id)
    if not store.scene_path(job_id).exists():
        raise HTTPException(404, pick("анализ ещё не готов", "the analysis is not ready yet"))
    return store.load_scene(job_id).model_dump(mode="json")


@app.put("/api/jobs/{job_id}/scene")
def put_scene(job_id: str, scene: dict) -> dict:
    state = _job(job_id)
    if state.status in ("processing", "rendering"):
        raise HTTPException(409, pick("задача сейчас обрабатывается", "the job is being processed"))
    try:
        parsed = Scene.model_validate(scene)
    except ValidationError as e:
        raise HTTPException(422, e.errors(include_url=False)) from None
    store.scene_path(job_id).write_text(parsed.model_dump_json(indent=1) + "\n", encoding="utf-8")
    return {"ok": True}


@app.post("/api/scene/rescore")
def rescore(scene: dict) -> dict:
    """Шкала и отсчёт до мата из категорий ходов — для редактора (сцена не сохраняется)."""
    from chessify.scoring import score_moves

    try:
        parsed = Scene.model_validate(scene)
    except ValidationError as e:
        raise HTTPException(422, e.errors(include_url=False)) from None
    return score_moves(parsed).model_dump(mode="json")


@app.post("/api/scene/pace")
def pace(scene: dict) -> dict:
    """Карточки по темпу: хук в начале, дальше примерно раз в 12 секунд — для редактора (не сохраняется)."""
    from chessify.pacing import pace_cards

    try:
        parsed = Scene.model_validate(scene)
    except ValidationError as e:
        raise HTTPException(422, e.errors(include_url=False)) from None
    return pace_cards(parsed).model_dump(mode="json")


class RenderRequest(BaseModel):
    length: str | None = None
    preset: str | None = None
    music: str | None = None  # "" — без музыки
    music_volume: float | None = None


@app.post("/api/jobs/{job_id}/render")
def render(job_id: str, req: RenderRequest) -> dict:
    state = _job(job_id)
    if state.status in ("queued", "processing", "rendering"):
        raise HTTPException(409, pick("задача уже в работе", "the job is already running"))
    if not store.scene_path(job_id).exists():
        raise HTTPException(409, pick("сначала нужен анализ", "the analysis is needed first"))
    changes = req.model_dump(exclude_unset=True)
    if "music" in changes:
        changes["music"] = changes["music"] or None
        _check_music(changes["music"])
    params = state.params.model_copy(update={k: v for k, v in changes.items() if v is not None or k == "music"})
    if params.length not in LENGTHS or params.preset not in ("final", "draft"):
        raise HTTPException(400, pick("неизвестная длина или качество", "unknown length or quality"))
    store.update(job_id, params=params)
    worker.submit("render", job_id)
    return store.get(job_id).model_dump()


@app.post("/api/jobs/{job_id}/retry")
def retry(job_id: str) -> dict:
    """Перезапуск после ошибки: готовые шаги (распознавание, анализ) берутся из кэша."""
    state = _job(job_id)
    if state.status != "error":
        raise HTTPException(409, pick("перезапускается только задача с ошибкой", "only a failed job can be retried"))
    worker.submit("render" if store.scene_path(job_id).exists() and not state.params.review else "process", job_id)
    return store.get(job_id).model_dump()


@app.get("/api/jobs/{job_id}/video/{name}")
def video(job_id: str, name: str) -> FileResponse:
    state = _job(job_id)
    if name not in state.outputs:
        raise HTTPException(404, pick("ролик не найден", "video not found"))
    return FileResponse(OUT_DIR / name, media_type="video/mp4", filename=name)


@app.get("/api/jobs/{job_id}/media/{name}")
def media(job_id: str, name: str) -> FileResponse:
    """Аватары и клип задачи — для предпросмотра в интерфейсе."""
    _job(job_id)
    from chessify.paths import RENDER_DIR

    path = (RENDER_DIR / "public" / "jobs" / job_id / name).resolve()
    if path.parent.name != job_id or not path.exists():
        raise HTTPException(404)
    return FileResponse(path)


def _check_music(name: str | None) -> None:
    if name and (Path(name).name != name or not (MUSIC_DIR / name).is_file()):
        raise HTTPException(400, pick(f"в библиотеке музыки нет {name}", f"no {name} in the music library"))


@app.get("/api/music")
def list_music() -> list[str]:
    if not MUSIC_DIR.exists():
        return []
    return sorted(p.name for p in MUSIC_DIR.iterdir() if p.suffix.lower() in MUSIC_EXT)


@app.post("/api/music", status_code=201)
async def upload_music(file: UploadFile = File(...)) -> dict:
    name = Path(file.filename or "").name
    if Path(name).suffix.lower() not in MUSIC_EXT:
        raise HTTPException(400, pick("нужен аудиофайл: ", "an audio file is needed: ") + ", ".join(sorted(MUSIC_EXT)))
    MUSIC_DIR.mkdir(parents=True, exist_ok=True)
    with (MUSIC_DIR / name).open("wb") as f:
        shutil.copyfileobj(file.file, f, length=4 * 1024 * 1024)
    return {"name": name}


@app.delete("/api/jobs/{job_id}")
def delete(job_id: str) -> dict:
    state = _job(job_id)
    if state.status in ("queued", "processing", "rendering"):
        raise HTTPException(409, pick("задача в работе", "the job is running"))
    from chessify.paths import RENDER_DIR

    for name in state.outputs:
        (OUT_DIR / name).unlink(missing_ok=True)
    shutil.rmtree(RENDER_DIR / "public" / "jobs" / job_id, ignore_errors=True)
    shutil.rmtree(store.path(job_id), ignore_errors=True)
    return {"ok": True}


# Длина ролика: пресеты из condense и «вся сцена» — проверка согласованности при импорте.
assert set(LENGTHS) == {"full", *PRESETS}

app.mount("/", StaticFiles(directory=STATIC, html=True), name="static")
