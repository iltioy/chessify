"""API веб-интерфейса без запуска сервера и без тяжёлых шагов: конвейер подменяется заглушкой."""

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from chessify.paths import RENDER_DIR
from chessify.schema import Scene
from chessify.web import app as webapp
from chessify.web import jobs as jobs_mod

REFERENCE = RENDER_DIR / "src" / "fixtures" / "reference.scene.json"


@pytest.fixture()
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    store = jobs_mod.JobStore(tmp_path / "jobs")
    worker = jobs_mod.Worker(store)
    monkeypatch.setattr(webapp, "store", store)
    monkeypatch.setattr(webapp, "worker", worker)
    monkeypatch.setattr(jobs_mod, "OUT_DIR", tmp_path / "out")
    monkeypatch.setattr(webapp, "OUT_DIR", tmp_path / "out")

    def fake_process(self, job_id: str) -> None:
        store.update(job_id, status="processing", step="2/5 распознавание")
        store.scene_path(job_id).write_text(REFERENCE.read_text(encoding="utf-8"), encoding="utf-8")
        store.update(job_id, status="review", step="проверьте ходы")

    def fake_render(scene: Scene, out: Path, preset: str, length: str, log, progress, **_) -> Path:
        progress(0.5)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(b"fake mp4")
        return out

    monkeypatch.setattr(jobs_mod.Worker, "_process", fake_process)
    monkeypatch.setattr("chessify.pipeline.render_scene", fake_render)
    with TestClient(webapp.app) as c:
        yield c, worker


def _create(c: TestClient) -> dict:
    r = c.post("/api/jobs", files={"video": ("Сцена 1.mp4", b"\x00" * 100, "video/mp4")},
               data={"series": "Во все тяжкие", "length": "shorts", "preset": "draft"})
    assert r.status_code == 201, r.text
    return r.json()


def test_config_and_static(client) -> None:
    c, _ = client
    cfg = c.get("/api/config").json()
    assert {"custom", "deepseek", "gemini", "openai", "openrouter", "anthropic", "claude"} == set(cfg["profiles"])
    assert cfg["profiles"]["custom"]["label"] == "Свой сервер"
    assert cfg["weights"]["best"] == 100
    assert "Сцена как шахматная партия" in c.get("/").text


def test_full_flow_review_edit_render(client) -> None:
    c, worker = client
    job = _create(c)
    jobs_mod.wait_idle(worker)
    state = c.get(f"/api/jobs/{job['id']}").json()
    assert state["status"] == "review" and state["has_scene"]

    scene = c.get(f"/api/jobs/{job['id']}/scene").json()
    scene["moves"][0]["comment"] = "Правка из интерфейса"
    assert c.put(f"/api/jobs/{job['id']}/scene", json=scene).status_code == 200

    r = c.post(f"/api/jobs/{job['id']}/render", json={"length": "reels"})
    assert r.status_code == 200
    jobs_mod.wait_idle(worker)
    state = c.get(f"/api/jobs/{job['id']}").json()
    assert state["status"] == "done"
    assert state["outputs"] == [f"{job['id']}_reels_draft.mp4"]
    assert c.get(f"/api/jobs/{job['id']}/video/{state['outputs'][0]}").content == b"fake mp4"
    saved = json.loads((webapp.store.scene_path(job["id"])).read_text(encoding="utf-8"))
    assert saved["moves"][0]["comment"] == "Правка из интерфейса"


def test_rejects_bad_input(client) -> None:
    c, worker = client
    r = c.post("/api/jobs", files={"video": ("notes.txt", b"x", "text/plain")}, data={"series": "X"})
    assert r.status_code == 400
    job = _create(c)
    jobs_mod.wait_idle(worker)
    bad = c.get(f"/api/jobs/{job['id']}/scene").json()
    bad["moves"][0]["category"] = "superb"
    assert c.put(f"/api/jobs/{job['id']}/scene", json=bad).status_code == 422
    assert c.get("/api/jobs/../etc").status_code == 404
    assert c.get(f"/api/jobs/{job['id']}/video/other.mp4").status_code == 404


def test_error_is_reported_and_delete(client, monkeypatch: pytest.MonkeyPatch) -> None:
    c, worker = client

    def boom(self, job_id: str) -> None:
        raise RuntimeError("нет ключей в .env: DEEPSEEK_API_KEY")

    monkeypatch.setattr(jobs_mod.Worker, "_process", boom)
    job = _create(c)
    jobs_mod.wait_idle(worker)
    state = c.get(f"/api/jobs/{job['id']}").json()
    assert state["status"] == "error" and "DEEPSEEK_API_KEY" in state["error"]
    assert c.delete(f"/api/jobs/{job['id']}").status_code == 200
    assert c.get(f"/api/jobs/{job['id']}").status_code == 404


def test_episode_choose_and_music(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Целая серия: поиск кандидатов → выбор → обработка выбранного отрезка → рендер с музыкой."""
    from chessify import pipeline
    from chessify.scenes import SceneCandidate

    store = jobs_mod.JobStore(tmp_path / "jobs")
    worker = jobs_mod.Worker(store)
    music_dir = tmp_path / "music"
    for mod in (webapp, pipeline):
        monkeypatch.setattr(mod, "MUSIC_DIR", music_dir)
    monkeypatch.setattr(webapp, "store", store)
    monkeypatch.setattr(webapp, "worker", worker)
    monkeypatch.setattr(jobs_mod, "OUT_DIR", tmp_path / "out")
    monkeypatch.setattr(webapp, "OUT_DIR", tmp_path / "out")

    seen: dict = {}

    def fake_find(self, source, cfg, roles, series, hint=""):
        cands = [SceneCandidate(start=196, end=554, title="Допрос", why="дуэль", sides="DEA / Майк", score=9,
                                excerpt="…")]
        (self.data / "candidates.json").write_text(json.dumps([c.model_dump() for c in cands]), encoding="utf-8")
        return cands

    def fake_process(self, source, cfg, roles, series, hint="", start=None, end=None, speakers=None):
        seen["range"] = (start, end)
        scene = Scene.model_validate_json(REFERENCE.read_text(encoding="utf-8"))
        (self.data / "scene.json").write_text(scene.model_dump_json(), encoding="utf-8")
        return scene

    def fake_render(scene, out, preset, length, log, progress, **_):
        seen["music"] = (scene.meta.music, scene.meta.music_volume)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(b"mp4")
        return out

    monkeypatch.setattr(pipeline.Job, "__init__", lambda self, job_id, log=print, **_: (
        setattr(self, "id", job_id), setattr(self, "data", store.path(job_id)), setattr(self, "log", log),
        setattr(self, "ui", "ru")) and None)
    monkeypatch.setattr(pipeline.Job, "find_scenes", fake_find)
    monkeypatch.setattr(pipeline.Job, "process", fake_process)
    monkeypatch.setattr(pipeline, "render_scene", fake_render)

    with TestClient(webapp.app) as c:
        assert c.post("/api/music", files={"file": ("theme.mp3", b"ID3", "audio/mpeg")}).status_code == 201
        assert c.get("/api/music").json() == ["theme.mp3"]
        assert c.post("/api/music", files={"file": ("x.exe", b"MZ", "application/octet-stream")}).status_code == 400

        r = c.post("/api/jobs", files={"video": ("episode.mkv", b"\x00" * 10, "video/x-matroska")},
                   data={"series": "Во все тяжкие", "mode": "episode", "profile": "claude", "music": "theme.mp3"})
        assert r.status_code == 201, r.text
        job_id = r.json()["id"]
        jobs_mod.wait_idle(worker)
        assert c.get(f"/api/jobs/{job_id}").json()["status"] == "choose"
        assert c.get(f"/api/jobs/{job_id}/candidates").json()[0]["title"] == "Допрос"

        assert c.post(f"/api/jobs/{job_id}/choose", json={"index": 5}).status_code == 400
        assert c.post(f"/api/jobs/{job_id}/choose", json={"index": 0}).status_code == 200
        jobs_mod.wait_idle(worker)
        assert seen["range"] == (196, 554)
        assert c.get(f"/api/jobs/{job_id}").json()["status"] == "review"

        assert c.post(f"/api/jobs/{job_id}/render", json={"music_volume": 0.2}).status_code == 200
        jobs_mod.wait_idle(worker)
        assert seen["music"] == ("music/theme.mp3", 0.2)
        assert c.post(f"/api/jobs/{job_id}/render", json={"music": "missing.mp3"}).status_code == 400
        assert c.post(f"/api/jobs/{job_id}/render", json={"music": ""}).status_code == 200
        jobs_mod.wait_idle(worker)
        assert seen["music"][0] is None


@pytest.fixture()
def settings_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    from chessify import settings

    path = tmp_path / "settings" / "settings.env"
    monkeypatch.setattr(settings, "SETTINGS_PATH", path)
    for key in settings.KEYS:
        monkeypatch.delenv(key, raising=False)
    yield path
    settings.save({}, list(settings.KEYS))  # вернуть окружение: снять всё, что перекрыли настройки


def _fields(resp: dict) -> dict:
    return {f["key"]: f for sec in resp["sections"] for f in sec["fields"]}


def test_settings_roundtrip(client, settings_file: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import os

    c, _ = client
    monkeypatch.setenv("HF_TOKEN", "hf_from_dotenv_value")
    got = c.get("/api/settings").json()
    assert [s["id"] for s in got["sections"]] == ["custom", "deepseek", "gemini", "openai", "openrouter", "anthropic",
                                                  "claude", "hf", "tiktok"]
    fields = _fields(got)
    assert fields["HF_TOKEN"]["source"] == "env" and "value" not in fields["HF_TOKEN"]
    assert next(s for s in got["sections"] if s["id"] == "hf")["ready"] is True

    secret = "sk-very-secret-key-1234"
    r = c.put("/api/settings", json={"values": {"CUSTOM_LLM_API_KEY": secret, "CUSTOM_LLM_BASE_URL": "http://llm:8000/v1",
                                                 "HF_TOKEN": "hf_from_web_abcd", "CHESSIFY_DEFAULT_PROFILE": "custom"}})
    assert r.status_code == 200
    assert secret not in r.text and "hf_from_web" not in r.text  # секреты наружу только маской
    fields = _fields(r.json())
    assert fields["CUSTOM_LLM_API_KEY"] == {**fields["CUSTOM_LLM_API_KEY"], "source": "web", "masked": "••••1234"}
    assert fields["CUSTOM_LLM_BASE_URL"]["value"] == "http://llm:8000/v1"
    assert next(s for s in r.json()["sections"] if s["id"] == "custom")["ready"] is True
    assert os.environ["CUSTOM_LLM_API_KEY"] == secret and os.environ["HF_TOKEN"] == "hf_from_web_abcd"
    assert settings_file.exists()

    cfg = c.get("/api/config").json()  # настройки действуют сразу: профиль и ключи
    assert cfg["default_profile"] == "custom" and cfg["profiles"]["custom"]["missing_keys"] == []

    c.put("/api/settings", json={"values": {"CUSTOM_LLM_API_KEY": ""}})  # пустое — не менять
    assert os.environ["CUSTOM_LLM_API_KEY"] == secret
    c.put("/api/settings", json={"clear": ["HF_TOKEN", "CUSTOM_LLM_API_KEY"]})
    assert os.environ["HF_TOKEN"] == "hf_from_dotenv_value"  # вернулось значение из .env
    assert "CUSTOM_LLM_API_KEY" not in os.environ


def test_settings_from_older_version_are_migrated(client, settings_file: Path) -> None:
    import os

    c, _ = client
    settings_file.parent.mkdir(parents=True, exist_ok=True)
    settings_file.write_text('WORK_LLM_BASE_URL="http://llm:8000/v1"\nWORK_LLM_API_KEY="old-key-123456789"\n'
                             'CHESSIFY_DEFAULT_PROFILE="work"\n', encoding="utf-8")
    got = c.get("/api/settings").json()
    assert got["default_profile"] == "custom"
    assert _fields(got)["CUSTOM_LLM_BASE_URL"]["value"] == "http://llm:8000/v1"
    assert os.environ["CUSTOM_LLM_API_KEY"] == "old-key-123456789"
    c.put("/api/settings", json={"values": {"HF_TOKEN": "hf_new_value_12345"}})  # при сохранении — уже под новыми именами
    assert "WORK_LLM" not in settings_file.read_text(encoding="utf-8")


@pytest.mark.parametrize("body", [
    {"values": {"SOMETHING_ELSE": "x"}},
    {"values": {"DASHSCOPE_API_KEY": "x"}},  # облачный Qwen убран
    {"values": {"CUSTOM_LLM_BASE_URL": "llm:8000"}},
    {"values": {"HF_TOKEN": "a\nB=c"}},
    {"values": {"CHESSIFY_DEFAULT_PROFILE": "nope"}},
])
def test_settings_rejects_bad_values(client, settings_file: Path, body: dict) -> None:
    c, _ = client
    assert c.put("/api/settings", json=body).status_code == 400
    assert not settings_file.exists()


def test_settings_check(client, settings_file: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    c, _ = client
    seen = {}

    def fake_check(cfg, provider, model=None):
        seen["provider"] = provider
        return {"ok": True, "lines": ["OK"], "models": ["qwen3-32b"]}

    monkeypatch.setattr("chessify.llm.check_provider", fake_check)
    assert c.post("/api/settings/check", json={"target": "custom"}).json()["models"] == ["qwen3-32b"]
    assert seen["provider"] == "custom"
    assert c.post("/api/settings/check", json={"target": "nope"}).status_code == 400
    hf = c.post("/api/settings/check", json={"target": "hf"}).json()  # без токена — без сети
    assert hf == {"ok": False, "lines": ["HF_TOKEN не задан"]}


def test_missing_keys_named_as_in_settings(client, settings_file: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    c, _ = client
    ds = c.get("/api/config").json()["profiles"]["deepseek"]
    assert ds["label"] == "DeepSeek" and "DEEPSEEK_API_KEY" in ds["missing_keys"]
    label = ds["missing_labels"][ds["missing_keys"].index("DEEPSEEK_API_KEY")]
    assert label == "DeepSeek → Ключ (DEEPSEEK_API_KEY)"


def test_rescore_recomputes_eval_from_categories(client) -> None:
    c, _ = client
    scene = json.loads(REFERENCE.read_text(encoding="utf-8"))
    for m in scene["moves"]:
        m["eval_after"] = 5.0  # как будто модель загнала шкалу в предел
    r = c.post("/api/scene/rescore", json=scene)
    assert r.status_code == 200
    assert max(abs(m["eval_after"]) for m in r.json()["moves"]) < 2
    assert c.post("/api/scene/rescore", json={"moves": []}).status_code == 422


def test_english_ui_messages_and_settings(client) -> None:
    c, _ = client
    en = {"X-Lang": "en"}
    assert c.get("/api/jobs/nope", headers=en).json()["detail"] == "job not found"
    assert c.get("/api/jobs/nope").json()["detail"] == "задача не найдена"  # без заголовка — по-русски
    cfg = c.get("/api/config", headers=en).json()
    assert cfg["lengths"]["full"] == "Whole scene" and cfg["profiles"]["custom"]["label"] == "Custom server"
    sections = {s["id"]: s for s in c.get("/api/settings", headers=en).json()["sections"]}
    assert sections["hf"]["title"] == "Speaker diarization" and sections["custom"]["fields"][0]["label"] == "API address"


def test_job_remembers_video_and_ui_language(client) -> None:
    c, _ = client
    r = c.post("/api/jobs", files={"video": ("scene.mp4", b"x", "video/mp4")},
               data={"series": "Breaking Bad", "language": "en"}, headers={"X-Lang": "en"})
    params = r.json()["params"]
    assert params["language"] == "en" and params["ui_lang"] == "en"
    r = c.post("/api/jobs", files={"video": ("scene.mp4", b"x", "video/mp4")}, data={"series": "Во все тяжкие"})
    assert r.json()["params"]["language"] == "ru"  # по умолчанию — язык интерфейса
