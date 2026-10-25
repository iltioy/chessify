"""Публикация в TikTok из веб-интерфейса: настройки, подключение аккаунта, публикация после рендера.

Сеть не нужна: модуль tiktok-publisher работает с поддельным клиентом TikTok.
"""

import threading
from pathlib import Path
from typing import cast

import pytest
from fastapi.testclient import TestClient

from chessify import tiktok
from chessify.paths import RENDER_DIR
from chessify.schema import Scene
from chessify.web import app as webapp
from chessify.web import jobs as jobs_mod
from tiktok_publisher import AccountStore, AuthError, Publisher
from tiktok_publisher.client import TikTokClient

REFERENCE = RENDER_DIR / "src" / "fixtures" / "reference.scene.json"


class FakeTikTok:
    """Тот же интерфейс, что у TikTokClient: что пришло — записывает, отвечает как TikTok."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, object]] = []
        self.unaudited = False

    def token(self, form: dict) -> dict:
        self.calls.append(("token", form))
        if form.get("code") == "bad":
            raise AuthError("invalid code", code="invalid_grant")
        return {"open_id": "u1", "access_token": "at-1", "expires_in": 86400, "refresh_token": "rt-1",
                "refresh_expires_in": 365 * 86400, "scope": "user.info.basic,video.publish,video.upload"}

    def revoke(self, client_key: str, client_secret: str, token: str) -> None:
        self.calls.append(("revoke", token))

    def creator_info(self, token: str) -> dict:
        return {"creator_username": "chess_tv", "creator_nickname": "Chess TV", "max_video_post_duration_sec": 600,
                "privacy_level_options": ["PUBLIC_TO_EVERYONE", "MUTUAL_FOLLOW_FRIENDS", "SELF_ONLY"]}

    def init_video(self, token: str, post_info: dict | None, source_info: dict, inbox: bool = False) -> dict:
        self.calls.append(("init", {"post": post_info, "source": source_info, "inbox": inbox}))
        if self.unaudited and post_info and post_info["privacy_level"] != "SELF_ONLY":
            from tiktok_publisher.errors import PostingRestricted

            raise PostingRestricted("unaudited", code="unaudited_client_can_only_post_to_private_accounts")
        return {"publish_id": "p-1", "upload_url": "https://upload.example/1"}

    def upload(self, url: str, path: Path, chunk_size: int, total: int) -> None:
        self.calls.append(("upload", path.read_bytes()))

    def status(self, token: str, publish_id: str) -> dict:
        return {"status": "PUBLISH_COMPLETE", "publicaly_available_post_id": [7001]}


@pytest.fixture()
def env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    store = jobs_mod.JobStore(tmp_path / "jobs")
    worker = jobs_mod.Worker(store)
    monkeypatch.setattr(webapp, "store", store)
    monkeypatch.setattr(webapp, "worker", worker)
    monkeypatch.setattr(jobs_mod, "OUT_DIR", tmp_path / "out")
    monkeypatch.setattr(webapp, "OUT_DIR", tmp_path / "out")
    monkeypatch.setattr(tiktok, "STORE_PATH", tmp_path / "settings" / "tiktok.json")
    fake = FakeTikTok()
    monkeypatch.setattr(tiktok, "publisher", lambda: Publisher(AccountStore(tiktok.STORE_PATH), cast(TikTokClient, fake), sleep=lambda s: None))

    def fake_process(self, job_id: str) -> None:
        store.scene_path(job_id).write_text(REFERENCE.read_text(encoding="utf-8"), encoding="utf-8")
        store.update(job_id, status="review", step="проверьте ходы")

    def fake_render(scene: Scene, out: Path, preset: str, length: str, log, progress, **_) -> Path:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(b"fake mp4")
        return out

    monkeypatch.setattr(jobs_mod.Worker, "_process", fake_process)
    monkeypatch.setattr("chessify.pipeline.render_scene", fake_render)
    with TestClient(webapp.app) as c:
        yield c, worker, fake


def _wait(worker: jobs_mod.Worker, c: TestClient, job_id: str) -> dict:
    jobs_mod.wait_idle(worker)
    for t in threading.enumerate():
        if t.name == f"tiktok-{job_id}":
            t.join(10)
    return c.get(f"/api/jobs/{job_id}").json()


def _connect(c: TestClient, base: str = "http://127.0.0.1:37415") -> dict:
    assert c.put("/api/tiktok/app", json={"client_key": "awkey123", "client_secret": "secret-value-1234"}).status_code == 200
    r = c.post("/api/tiktok/connect", json={"account": "main"}, headers={"host": base.split("//")[1]})
    assert r.status_code == 200, r.text
    return r.json()


def test_app_settings_mask_the_secret(env) -> None:
    c, _, _ = env
    assert c.get("/api/tiktok").json()["app"] is None
    assert c.put("/api/tiktok/app", json={"client_key": "awkey", "client_secret": ""}).status_code == 400
    st = c.put("/api/tiktok/app", json={"client_key": "awkey123", "client_secret": "secret-value-1234"}).json()
    assert st["app"] == {"client_key": "awkey123", "secret_masked": "••••1234"}
    # пустой секрет — оставить прежний
    c.put("/api/tiktok/app", json={"client_key": "awkey456"})
    assert AccountStore(tiktok.STORE_PATH).get_app("chessify").client_secret == "secret-value-1234"
    assert "secret-value" not in c.get("/api/tiktok").text
    sections = {s["id"]: s for s in c.get("/api/settings").json()["sections"]}
    assert sections["tiktok"]["kind"] == "publish" and sections["tiktok"]["ready"] is False


def test_connect_via_callback(env) -> None:
    c, _, fake = env
    res = _connect(c)
    assert res["local"] and res["redirect_uri"] == "http://127.0.0.1:37415/api/tiktok/callback/"
    assert "client_key=awkey123" in res["url"] and "code_challenge=" in res["url"]
    state = tiktok.parse_callback(res["url"])["state"]
    page = c.get("/api/tiktok/callback/", params={"code": "c-1", "state": state})
    assert page.status_code == 200 and "@chess_tv" in page.text
    assert fake.calls[0][1]["redirect_uri"] == res["redirect_uri"]  # type: ignore[index]
    accounts = c.get("/api/tiktok").json()["accounts"]
    assert [a["username"] for a in accounts] == ["chess_tv"]
    assert "access_token" not in accounts[0]
    # повторно тот же state не принимается, отказ TikTok — понятная ошибка
    assert c.get("/api/tiktok/callback/", params={"code": "c-1", "state": state}).status_code == 400
    denied = c.get("/api/tiktok/callback/", params={"error": "access_denied", "error_description": "user cancelled"})
    assert denied.status_code == 400 and "user cancelled" in denied.text


def test_connect_from_another_machine_by_pasting_the_address(env) -> None:
    c, _, _ = env
    res = _connect(c, "http://192.168.1.20:37415")
    assert not res["local"] and res["redirect_uri"].startswith("http://127.0.0.1:37415/")
    state = tiktok.parse_callback(res["url"])["state"]
    st = c.post("/api/tiktok/finish", json={"url": f"{res['redirect_uri']}?code=c-2&state={state}&scopes=x"}).json()
    assert st["accounts"][0]["name"] == "main"
    assert c.post("/api/tiktok/finish", json={"url": "http://127.0.0.1/?code=bad&state=nope"}).status_code == 400


def test_account_privacy_and_disconnect(env) -> None:
    c, _, fake = env
    res = _connect(c)
    c.get("/api/tiktok/callback/", params={"code": "c", "state": tiktok.parse_callback(res["url"])["state"]})
    st = c.put("/api/tiktok/accounts/main", json={"default_privacy": "PUBLIC_TO_EVERYONE"}).json()
    assert st["accounts"][0]["default_privacy"] == "PUBLIC_TO_EVERYONE"
    assert c.put("/api/tiktok/accounts/main", json={"default_privacy": "NOPE"}).status_code == 400
    assert c.delete("/api/tiktok/accounts/main").json()["accounts"] == []
    assert ("revoke", "at-1") in fake.calls
    assert c.delete("/api/tiktok/accounts/main").status_code == 404


def _connected(c: TestClient) -> None:
    res = _connect(c)
    c.get("/api/tiktok/callback/", params={"code": "c", "state": tiktok.parse_callback(res["url"])["state"]})


def test_auto_publish_after_render_once(env) -> None:
    c, worker, fake = env
    _connected(c)
    c.put("/api/tiktok/accounts/main", json={"default_privacy": "PUBLIC_TO_EVERYONE"})
    r = c.post("/api/jobs", files={"video": ("scene.mp4", b"\x00" * 10, "video/mp4")},
               data={"series": "Во все тяжкие", "length": "shorts", "review": "false", "tiktok_account": "main"})
    assert r.status_code == 201, r.text
    job_id = r.json()["id"]
    # без review рендер идёт сразу; заглушка _process его не вызывает — запускаем, как кнопка «Собрать»
    jobs_mod.wait_idle(worker)
    c.post(f"/api/jobs/{job_id}/render", json={})
    job = _wait(worker, c, job_id)
    assert job["status"] == "done"
    info = job["tiktok"]
    assert info["state"] == "done" and info["status"] == "PUBLISH_COMPLETE"
    assert info["url"] == "https://www.tiktok.com/@chess_tv/video/7001"
    assert info["privacy"] == "PUBLIC_TO_EVERYONE" and info["video"] == job["outputs"][0]
    init = next(x for name, x in fake.calls if name == "init")
    assert init["post"]["title"].startswith("Майк против агентов DEA: допрос") and "#ВоВсеТяжкие" in init["post"]["title"]  # type: ignore[index]
    assert ("upload", b"fake mp4") in fake.calls
    # повторный рендер не публикует снова
    c.post(f"/api/jobs/{job_id}/render", json={"preset": "draft"})
    _wait(worker, c, job_id)
    assert sum(1 for name, _ in fake.calls if name == "init") == 1


def test_manual_publish_unaudited_inbox_and_errors(env) -> None:
    c, worker, fake = env
    r = c.post("/api/jobs", files={"video": ("scene.mp4", b"\x00" * 10, "video/mp4")}, data={"series": "Breaking Bad"})
    job_id = r.json()["id"]
    jobs_mod.wait_idle(worker)
    assert c.post(f"/api/jobs/{job_id}/tiktok", json={"account": "main"}).status_code == 409  # ролика ещё нет
    c.post(f"/api/jobs/{job_id}/render", json={})
    job = _wait(worker, c, job_id)
    assert job["tiktok"] is None and job["tiktok_caption"]
    assert c.post(f"/api/jobs/{job_id}/tiktok", json={"account": "main"}).status_code == 400  # не подключён

    _connected(c)
    fake.unaudited = True
    r = c.post(f"/api/jobs/{job_id}/tiktok", json={"account": "main", "caption": "Своя подпись #chess",
                                                   "privacy": "PUBLIC_TO_EVERYONE"})
    assert r.status_code == 200, r.text
    info = _wait(worker, c, job_id)["tiktok"]
    assert info["state"] == "done" and info["privacy"] == "SELF_ONLY" and info["note"]
    assert info["caption"] == "Своя подпись #chess"

    r = c.post(f"/api/jobs/{job_id}/tiktok", json={"account": "main", "mode": "inbox"})
    info = _wait(worker, c, job_id)["tiktok"]
    assert info["mode"] == "inbox" and fake.calls[-2][0] == "init" and fake.calls[-2][1]["inbox"]  # type: ignore[index]

    refreshed = c.post(f"/api/jobs/{job_id}/tiktok/refresh").json()["tiktok"]
    assert refreshed["post_ids"] == ["7001"]

    fake.init_video = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("network down"))  # type: ignore[method-assign]
    c.post(f"/api/jobs/{job_id}/tiktok", json={"account": "main"})
    job = _wait(worker, c, job_id)
    assert job["status"] == "done" and job["tiktok"]["state"] == "error" and "network down" in job["tiktok"]["error"]


def test_default_caption_languages() -> None:
    scene = Scene.model_validate_json(REFERENCE.read_text(encoding="utf-8"))
    assert tiktok.default_caption(scene).endswith("#ВоВсеТяжкие #шахматы #сериалы")
    en = scene.model_copy(update={"meta": scene.meta.model_copy(update={"language": "en", "series": "Breaking Bad"})})
    assert tiktok.default_caption(en).endswith("#BreakingBad #chess #tvshow")
