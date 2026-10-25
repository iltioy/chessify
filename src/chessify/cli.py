import json
from pathlib import Path

import typer

from chessify import doctor as doctor_mod
from chessify.paths import GENERATED_DIR, RENDER_DIR, ROOT
from chessify.schema import Scene
from chessify.scoring import EVAL_LIMIT, WEIGHTS
from chessify.timing import TIMING

MUSIC_HELP = "Фоновая музыка: имя трека из render/public/music или путь к аудиофайлу"
LENGTH_HELP = "full — вся сцена; shorts (≤60 с), reels (≤90 с), short3 (≤3 мин) — лучшие пары ходов"

app = typer.Typer(no_args_is_help=True, help="Сцена из сериала как шахматная партия.")


@app.command("export-schema")
def export_schema() -> None:
    """Экспортировать JSON Schema сцены и веса точности для шаблона Remotion."""
    GENERATED_DIR.mkdir(parents=True, exist_ok=True)
    schema_path = GENERATED_DIR / "scene.schema.json"
    schema_path.write_text(json.dumps(Scene.model_json_schema(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    scoring = {"weights": {c.value: w for c, w in WEIGHTS.items()}, "evalLimit": EVAL_LIMIT}
    (GENERATED_DIR / "scoring.json").write_text(json.dumps(scoring, indent=2) + "\n", encoding="utf-8")
    (GENERATED_DIR / "timing.json").write_text(json.dumps(TIMING, indent=2) + "\n", encoding="utf-8")
    typer.echo(f"Записано: {schema_path.relative_to(RENDER_DIR.parent)}, scoring.json")


@app.command()
def validate(scene: Path) -> None:
    """Проверить JSON сцены по схеме."""
    Scene.model_validate_json(scene.read_text(encoding="utf-8"))
    typer.echo("OK")


@app.command()
def transcribe(
    audio: Path,
    out: Path = typer.Option(..., help="Куда записать слова (JSON)"),
    model: str = typer.Option("large-v3"),
    device: str = typer.Option("auto", help="cuda, cpu или auto"),
    language: str = typer.Option("ru"),
) -> None:
    """Распознать речь: слова с таймкодами."""
    from chessify.asr import ADAPTERS

    words = ADAPTERS["faster_whisper"](model=model, device=device).transcribe(audio, language)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps([w.model_dump() for w in words], ensure_ascii=False, indent=1), encoding="utf-8")
    typer.echo(f"{len(words)} слов → {out}")


@app.command()
def analyze(
    words: Path = typer.Argument(..., help="Слова со спикерами (JSON) или готовая сцена — из неё берутся слова"),
    out: Path = typer.Option(..., help="Куда записать сцену (JSON)"),
    series: str = typer.Option(..., help="Название сериала"),
    clip: str = typer.Option(..., help="Видео сцены относительно render/public"),
    background: str | None = typer.Option(None, help="Размытый фон относительно render/public"),
    profile: str | None = typer.Option(None, help="Профиль из config/providers.yaml"),
    set_: list[str] = typer.Option([], "--set", help="Подмена роли: grade=claude"),
    hint: str = typer.Option("", help="Подсказка модели о сцене"),
    no_examples: bool = typer.Option(False, help="Не давать модели примеры из референса (для честной оценки на нём)"),
    language: str = typer.Option("ru", help="Язык ролика: ru или en (речь, тексты модели, надписи)"),
) -> None:
    """Разобрать диалог как шахматную партию: ходы, оценки, комментарии."""
    from chessify.analysis import analyze as run_analysis
    from chessify.analysis import load_words
    from chessify.config import load_config
    from chessify.llm import LLMRouter
    from chessify.schema import Meta

    cfg = load_config()
    roles = cfg.profile(profile, dict(s.split("=", 1) for s in set_))
    if missing := [k for k in cfg.missing_keys(roles) if k != "HF_TOKEN"]:
        raise typer.BadParameter(f"нет ключей: {', '.join(missing)} (.env или «Настройки» веб-интерфейса)")
    raw = json.loads(words.read_text(encoding="utf-8"))
    word_list = load_words(words) if isinstance(raw, list) else Scene.model_validate(raw).words
    router = LLMRouter(cfg, roles)
    from chessify.pipeline import KICKER

    from chessify.i18n import norm

    lang = norm(language)
    meta = Meta(series=series, title="", clip=clip, background=background, language=lang, kicker=KICKER[lang])
    scene = run_analysis(router, word_list, meta, hint=hint, exclude_reference=no_examples)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(scene.model_dump_json(indent=1) + "\n", encoding="utf-8")
    t = router.total
    typer.echo(f"{len(scene.moves)} ходов → {out}; токены {t.input_tokens}/{t.output_tokens}, ≈ ${t.cost_usd:.3f}")


@app.command("compare")
def compare(
    generated: Path,
    reference: Path = typer.Option(RENDER_DIR / "src" / "fixtures" / "reference.scene.json"),
    from_move: int = typer.Option(1, help="Оценивать с этого хода (ходы до него модель видела как примеры)"),
) -> None:
    """Сравнить разбор модели с эталонной разметкой."""
    from chessify.evaluate import report

    load = lambda p: Scene.model_validate_json(p.read_text(encoding="utf-8"))  # noqa: E731
    typer.echo(report(load(reference), load(generated), from_move))


@app.command("llm-check")
def llm_check(
    provider: str = typer.Option("custom", help="Провайдер из config/providers.yaml"),
    model: str | None = typer.Option(None, help="Модель из config/providers.yaml; по умолчанию первая этого провайдера"),
) -> None:
    """Проверить подключение к LLM: список моделей на сервере и пробный ответ в JSON."""
    from chessify.config import load_config
    from chessify.llm import check_provider

    result = check_provider(load_config(), provider, model)
    for line in result["lines"]:
        typer.echo(line)
    if not result["ok"]:
        raise typer.Exit(1)


@app.command()
def doctor() -> None:
    """Проверить окружение (GPU, CUDA, NVENC, Node, Remotion)."""
    marks = {True: "OK  ", False: "FAIL", None: "SKIP"}
    results = doctor_mod.run_all()
    for c in results:
        typer.echo(f"[{marks[c.ok]}] {c.name}: {c.detail}")
    if any(c.ok is False for c in results):
        raise typer.Exit(1)


@app.command()
def render(
    scene: Path = typer.Argument(..., help="JSON сцены"),
    out: Path = typer.Option(Path("out/video.mp4"), help="Куда сохранить ролик"),
    preset: str = typer.Option("final", help="final (1080×1920) или draft (720×1280)"),
    length: str = typer.Option("full", help=LENGTH_HELP),
    music: str | None = typer.Option(None, help=MUSIC_HELP),
    music_volume: float | None = typer.Option(None, help="Громкость музыки под речью, 0–1 (по умолчанию 0.12)"),
) -> None:
    """Отрендерить ролик через Remotion."""
    from chessify.pipeline import add_music, render_scene

    data = add_music(Scene.model_validate_json(scene.read_text(encoding="utf-8")), music, music_volume)
    render_scene(data, out, preset, length, log=typer.echo)


@app.command()
def run(
    video: Path = typer.Argument(..., help="Фрагмент сериала"),
    series: str = typer.Option(..., help="Название сериала"),
    out: Path | None = typer.Option(None, help="Готовый ролик; по умолчанию out/<id>.mp4"),
    job: str | None = typer.Option(None, help="Имя задачи; по умолчанию имя файла"),
    start: float | None = typer.Option(None, help="Начало сцены в исходнике, секунды"),
    end: float | None = typer.Option(None, help="Конец сцены в исходнике, секунды"),
    profile: str | None = typer.Option(None, help="Профиль из config/providers.yaml"),
    set_: list[str] = typer.Option([], "--set", help="Подмена роли: grade=claude"),
    hint: str = typer.Option("", help="Подсказка модели о сцене"),
    speakers: int | None = typer.Option(None, help="Сколько человек говорит в сцене, если известно"),
    preset: str = typer.Option("final", help="final (1080×1920) или draft (720×1280)"),
    length: str = typer.Option("full", help=LENGTH_HELP),
    auto_scene: bool = typer.Option(False, help="На входе целая серия: найти лучшую сцену-дуэль и взять её"),
    music: str | None = typer.Option(None, help=MUSIC_HELP),
    music_volume: float | None = typer.Option(None, help="Громкость музыки под речью, 0–1 (по умолчанию 0.12)"),
    language: str = typer.Option("ru", help="Язык ролика: ru или en (речь, тексты модели, надписи)"),
    tiktok: str | None = typer.Option(None, help="Опубликовать ролик в этот аккаунт TikTok (chessify tiktok account list)"),
    tiktok_caption: str = typer.Option("", help="Подпись в TikTok; пусто — заголовок ролика и хэштеги"),
    tiktok_inbox: bool = typer.Option(False, help="Не публиковать сразу, а отправить в черновики TikTok"),
) -> None:
    """Всё сразу: видео → распознавание → спикеры → анализ → ролик. Готовые шаги пропускаются."""
    from chessify.config import load_config

    cfg = load_config()
    roles = cfg.profile(profile, dict(s.split("=", 1) for s in set_))
    if missing := [k for k in cfg.missing_keys(roles) if k != "HF_TOKEN"]:
        raise typer.BadParameter(f"нет ключей: {', '.join(missing)} (.env или «Настройки» веб-интерфейса)")
    result = _run_one(video, cfg, roles, job or video.stem, out, series=series, start=start, end=end, hint=hint,
                      speakers=speakers, preset=preset, length=length, auto_scene=auto_scene, music=music,
                      music_volume=music_volume, language=language)
    if tiktok:
        from chessify import tiktok as tt
        from chessify.pipeline import Job

        scene = Scene.model_validate_json((Job(job or video.stem).data / "scene.json").read_text(encoding="utf-8"))
        typer.echo(f"TikTok: загружаю в аккаунт «{tiktok}»…")
        r = tt.publisher().publish(tiktok, result, tt.PostOptions(
            title=tiktok_caption or tt.default_caption(scene), mode="inbox" if tiktok_inbox else "direct"))
        typer.echo(f"TikTok: {r.status}" + (f" — {r.url}" if r.url else "") + (f" ({r.note})" if r.note else ""))
        if not r.ok:
            raise typer.Exit(1)


def _run_one(video: Path, cfg, roles: dict[str, str], job_id: str, out: Path | None, *, series: str,
             start: float | None, end: float | None, hint: str, speakers: int | None, preset: str, length: str,
             auto_scene: bool, music: str | None, music_volume: float | None, language: str = "ru") -> Path:
    from chessify.pipeline import Job, add_music, render_scene

    j = Job(job_id, log=typer.echo, language=language)
    if auto_scene and start is None and end is None:
        candidates = j.find_scenes(video, cfg, roles, series, hint)
        if not candidates:
            raise RuntimeError("подходящих сцен-дуэлей не найдено")
        best = candidates[0]
        typer.echo(f"Сцена: {best.title} ({best.start:.0f}–{best.end:.0f} с, оценка {best.score}/10)")
        start, end = best.start, best.end
    scene = add_music(j.process(video, cfg, roles, series, hint, start, end, speakers), music, music_volume)
    return render_scene(scene, out or ROOT / "out" / f"{j.id}.mp4", preset, length, log=typer.echo)


VIDEO_EXT = {".mp4", ".mkv", ".mov", ".avi", ".webm", ".m4v"}


@app.command()
def batch(
    inputs: list[Path] = typer.Argument(..., help="Видеофайлы или папки с ними"),
    series: str = typer.Option(..., help="Название сериала (одно на весь пакет)"),
    profile: str | None = typer.Option(None, help="Профиль из config/providers.yaml"),
    set_: list[str] = typer.Option([], "--set", help="Подмена роли: grade=claude"),
    hint: str = typer.Option("", help="Подсказка модели о сценах"),
    preset: str = typer.Option("final", help="final (1080×1920) или draft (720×1280)"),
    length: str = typer.Option("full", help=LENGTH_HELP),
    auto_scene: bool = typer.Option(False, help="Файлы — целые серии: в каждой найти лучшую сцену-дуэль"),
    music: str | None = typer.Option(None, help=MUSIC_HELP),
    music_volume: float | None = typer.Option(None, help="Громкость музыки под речью, 0–1"),
    language: str = typer.Option("ru", help="Язык ролика: ru или en (речь, тексты модели, надписи)"),
) -> None:
    """Пакет: обработать несколько файлов по очереди. Ошибка в одном файле не останавливает остальные."""
    from chessify.config import load_config

    files = sorted({f for p in inputs for f in ([p] if p.is_file() else p.rglob("*"))
                    if f.is_file() and f.suffix.lower() in VIDEO_EXT})
    if not files:
        raise typer.BadParameter("видеофайлов не найдено")
    cfg = load_config()
    roles = cfg.profile(profile, dict(s.split("=", 1) for s in set_))
    if missing := [k for k in cfg.missing_keys(roles) if k != "HF_TOKEN"]:
        raise typer.BadParameter(f"нет ключей: {', '.join(missing)} (.env или «Настройки» веб-интерфейса)")
    results: list[tuple[Path, str]] = []
    for i, f in enumerate(files, 1):
        typer.echo(f"\n=== {i}/{len(files)}: {f.name} ===")
        try:
            out = _run_one(f, cfg, roles, f.stem, None, series=series, start=None, end=None, hint=hint,
                           speakers=None, preset=preset, length=length, auto_scene=auto_scene, music=music,
                           music_volume=music_volume, language=language)
            results.append((f, f"готово → {out}"))
        except Exception as e:  # noqa: BLE001 — пакет продолжается
            results.append((f, f"ОШИБКА: {e}"))
            typer.echo(f"ОШИБКА: {e}")
    typer.echo("\nИтог:")
    for f, r in results:
        typer.echo(f"  {f.name}: {r}")
    if any(r.startswith("ОШИБКА") for _, r in results):
        raise typer.Exit(1)


@app.command("find-scenes")
def find_scenes_cmd(
    video: Path = typer.Argument(..., help="Целая серия"),
    series: str = typer.Option(..., help="Название сериала"),
    job: str | None = typer.Option(None, help="Имя задачи; по умолчанию имя файла"),
    profile: str | None = typer.Option(None, help="Профиль из config/providers.yaml"),
    hint: str = typer.Option("", help="Подсказка модели: какую сцену искать"),
    language: str = typer.Option("ru", help="Язык ролика: ru или en (речь, тексты модели, надписи)"),
) -> None:
    """Найти в серии сцены-дуэли для ролика (до трёх кандидатов)."""
    from chessify.config import load_config
    from chessify.pipeline import Job

    cfg = load_config()
    roles = cfg.profile(profile)
    candidates = Job(job or video.stem, log=typer.echo, language=language).find_scenes(video, cfg, roles, series, hint)
    for i, c in enumerate(candidates, 1):
        typer.echo(f"\n{i}. {c.title} — {c.score}/10, {c.start:.1f}–{c.end:.1f} с ({c.end - c.start:.0f} с)")
        typer.echo(f"   {c.why}\n   Стороны: {c.sides}\n   «{c.excerpt}»")
    if candidates:
        typer.echo(f"\nДальше: chessify run {video} --series \"{series}\" --start {candidates[0].start} --end {candidates[0].end}")


@app.command(context_settings={"allow_extra_args": True, "ignore_unknown_options": True}, add_help_option=False)
def tiktok(ctx: typer.Context) -> None:
    """Аккаунты TikTok: команды модуля tiktok-publisher с хранилищем Chessify (settings/tiktok.json).

    Например: chessify tiktok account list; chessify tiktok account connect main --app chessify.
    """
    from chessify import tiktok as tt
    from tiktok_publisher.cli import main

    raise typer.Exit(main(["--store", str(tt.STORE_PATH), *ctx.args]))


@app.command()
def web(host: str = typer.Option("127.0.0.1"), port: int = typer.Option(37415)) -> None:
    """Веб-интерфейс."""
    import uvicorn

    uvicorn.run("chessify.web.app:app", host=host, port=port)
