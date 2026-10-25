"""Модуль целиком на поддельном транспорте: вход, продление токенов, публикация, ошибки."""

import json
import urllib.parse
from pathlib import Path

import pytest

from tiktok_publisher import (Account, AccountStore, App, AuthError, ConfigError, PostOptions, PrivacyNotAllowed,
                              Publisher)
from tiktok_publisher.client import CHUNK, TikTokClient, chunk_plan


class FakeTransport:
    """Отвечает как TikTok по URL; запоминает запросы."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict, bytes | None]] = []
        self.creator = {"creator_username": "chess_tv", "creator_nickname": "Chess TV",
                        "privacy_level_options": ["PUBLIC_TO_EVERYONE", "MUTUAL_FOLLOW_FRIENDS", "SELF_ONLY"],
                        "max_video_post_duration_sec": 600}
        self.unaudited = False
        self.statuses = ["PROCESSING_UPLOAD", "PUBLISH_COMPLETE"]
        self.token_n = 0

    def request(self, method, url, headers, body, timeout):
        self.calls.append((method, url, headers, body))
        ok = {"error": {"code": "ok", "message": "", "log_id": "L"}}
        if url.endswith("/v2/oauth/token/"):
            self.token_n += 1
            form = dict(urllib.parse.parse_qsl(body.decode()))
            if form.get("code") == "bad":
                return 400, {}, json.dumps({"error": "invalid_grant", "error_description": "bad code"}).encode()
            return 200, {}, json.dumps({"access_token": f"act{self.token_n}", "expires_in": 86400, "open_id": "oid",
                                        "refresh_token": f"rft{self.token_n}", "refresh_expires_in": 31536000,
                                        "scope": "user.info.basic,video.publish"}).encode()
        if url.endswith("/creator_info/query/"):
            return 200, {}, json.dumps({"data": self.creator, **ok}).encode()
        if url.endswith("/publish/video/init/") or url.endswith("/inbox/video/init/"):
            post = json.loads(body).get("post_info", {})
            if self.unaudited and post.get("privacy_level") != "SELF_ONLY":
                err = {"code": "unaudited_client_can_only_post_to_private_accounts", "message": "private only"}
                return 403, {}, json.dumps({"error": err}).encode()
            return 200, {}, json.dumps({"data": {"publish_id": "p1", "upload_url": "https://up.example/u"}, **ok}).encode()
        if url.startswith("https://up.example/"):
            last = headers["Content-Range"].split("/")[0].split("-")[1]
            total = headers["Content-Range"].split("/")[1]
            return (201 if int(last) == int(total) - 1 else 206), {}, b""
        if url.endswith("/status/fetch/"):
            status = self.statuses.pop(0) if len(self.statuses) > 1 else self.statuses[0]
            data: dict[str, object] = {"status": status}
            if status == "PUBLISH_COMPLETE":
                data["publicaly_available_post_id"] = [7300000000000000001]
            return 200, {}, json.dumps({"data": data, **ok}).encode()
        if url.endswith("/oauth/revoke/"):
            return 200, {}, b""
        raise AssertionError(url)


class Clock:
    def __init__(self) -> None:
        self.t = 1_000_000.0

    def __call__(self) -> float:
        return self.t


@pytest.fixture()
def env(tmp_path: Path):
    transport, clock = FakeTransport(), Clock()
    store = AccountStore(tmp_path / "store.json")
    store.set_app(App("default", "ck", "cs", "http://127.0.0.1:3455/callback/"))
    pub = Publisher(store, TikTokClient(transport), clock=clock, sleep=lambda s: None)
    return pub, transport, clock, tmp_path


def connect(pub: Publisher, name: str = "main") -> Account:
    url = pub.start_connect(name)
    q = dict(urllib.parse.parse_qsl(urllib.parse.urlparse(url).query))
    assert q["client_key"] == "ck" and q["code_challenge_method"] == "S256" and len(q["code_challenge"]) == 64
    return pub.finish_connect(q["state"], "the-code")


def test_connect_saves_tokens_and_creator(env) -> None:
    pub, transport, _, tmp = env
    acc = connect(pub)
    assert acc.username == "chess_tv" and acc.access_token == "act1" and acc.default_privacy == "SELF_ONLY"
    form = dict(urllib.parse.parse_qsl(transport.calls[0][3].decode()))
    assert form["grant_type"] == "authorization_code" and form["code_verifier"] and form["redirect_uri"].endswith("/callback/")
    with pytest.raises(ConfigError):  # state одноразовый
        pub.finish_connect("unknown-state", "x")
    assert (tmp / "store.json").stat().st_mode & 0o077 == 0  # только владелец


def test_bad_code_is_auth_error(env) -> None:
    pub, *_ = env
    url = pub.start_connect("main")
    state = dict(urllib.parse.parse_qsl(urllib.parse.urlparse(url).query))["state"]
    with pytest.raises(AuthError):
        pub.finish_connect(state, "bad")


def test_token_refreshes_and_rotates(env) -> None:
    pub, transport, clock, _ = env
    connect(pub)
    assert pub.access_token("main") == "act1"
    clock.t += 86400 - 60  # до конца меньше пяти минут
    assert pub.access_token("main") == "act2"
    acc = pub.store.get_account("main")
    assert acc.refresh_token == "rft2"  # новый refresh_token сохранён
    form = dict(urllib.parse.parse_qsl(transport.calls[-1][3].decode()))
    assert form == {"client_key": "ck", "client_secret": "cs", "grant_type": "refresh_token", "refresh_token": "rft1"}


def test_publish_uploads_in_chunks_and_returns_url(env) -> None:
    pub, transport, _, tmp = env
    connect(pub)
    pub.store.set_default_privacy("main", "PUBLIC_TO_EVERYONE")
    video = tmp / "v.mp4"
    video.write_bytes(b"x" * (CHUNK * 2 + CHUNK // 2 + 7))  # больше 64 МБ — частями
    r = pub.publish("main", video, PostOptions(title="Партия #шахматы", is_aigc=True))
    assert r.ok and r.status == "PUBLISH_COMPLETE" and r.privacy == "PUBLIC_TO_EVERYONE"
    assert r.url == "https://www.tiktok.com/@chess_tv/video/7300000000000000001"
    init = next(json.loads(c[3]) for c in transport.calls if c[1].endswith("/publish/video/init/"))
    assert init["source_info"] == {"source": "FILE_UPLOAD", "video_size": video.stat().st_size,
                                   "chunk_size": CHUNK, "total_chunk_count": 2}
    assert init["post_info"]["title"] == "Партия #шахматы" and init["post_info"]["is_aigc"] is True
    puts = [c for c in transport.calls if c[0] == "PUT"]
    assert [p[2]["Content-Range"] for p in puts] == [f"bytes 0-{CHUNK - 1}/{video.stat().st_size}",
                                                    f"bytes {CHUNK}-{video.stat().st_size - 1}/{video.stat().st_size}"]
    assert sum(len(p[3]) for p in puts) == video.stat().st_size


def test_small_video_is_single_chunk() -> None:
    assert chunk_plan(3 * 1024 * 1024) == (3 * 1024 * 1024, 1)
    assert chunk_plan(64 * 1024 * 1024) == (64 * 1024 * 1024, 1)
    size, n = chunk_plan(4 * 1024 ** 3 - 1)
    assert size == CHUNK and n <= 1000


def test_unaudited_app_falls_back_to_private(env) -> None:
    pub, transport, _, tmp = env
    connect(pub)
    transport.unaudited = True
    video = tmp / "v.mp4"
    video.write_bytes(b"x" * 1000)
    r = pub.publish("main", video, PostOptions(privacy="PUBLIC_TO_EVERYONE"))
    assert r.privacy == "SELF_ONLY" and r.note and "audit" in r.note
    with pytest.raises(Exception, match="private only"):
        pub.publish("main", video, PostOptions(privacy="PUBLIC_TO_EVERYONE", private_if_unaudited=False))


def test_privacy_and_duration_are_checked(env) -> None:
    pub, transport, _, tmp = env
    connect(pub)
    video = tmp / "v.mp4"
    video.write_bytes(b"x" * 1000)
    with pytest.raises(PrivacyNotAllowed) as e:
        pub.publish("main", video, PostOptions(privacy="FOLLOWER_OF_CREATOR"))
    assert "SELF_ONLY" in e.value.allowed
    with pytest.raises(ConfigError, match="allows up to 600s"):
        pub.publish("main", video, PostOptions(duration_sec=900))
    with pytest.raises(ConfigError, match="title"):
        pub.publish("main", video, PostOptions(title="x" * 2201))


def test_inbox_mode_and_no_wait(env) -> None:
    pub, transport, _, tmp = env
    connect(pub)
    transport.statuses = ["SEND_TO_USER_INBOX"]
    video = tmp / "v.mp4"
    video.write_bytes(b"x" * 1000)
    assert pub.publish("main", video, PostOptions(mode="inbox"), wait=False).status == "PROCESSING_UPLOAD"
    r = pub.publish("main", video, PostOptions(mode="inbox"))
    assert r.status == "SEND_TO_USER_INBOX" and r.ok
    assert any(c[1].endswith("/inbox/video/init/") for c in transport.calls)


def test_accounts_are_separate_and_disconnect(env) -> None:
    pub, *_ = env
    connect(pub, "chessify")
    connect(pub, "other-service")
    assert {a.name for a in pub.store.list_accounts()} == {"chessify", "other-service"}
    assert "access_token" not in pub.store.get_account("chessify").public()
    pub.disconnect("chessify")
    assert [a.name for a in pub.store.list_accounts()] == ["other-service"]


def test_cli_json(env, capsys) -> None:
    from tiktok_publisher.cli import main

    pub, _, _, tmp = env
    assert main(["--store", str(tmp / "store.json"), "--json", "app", "list"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out[0]["client_secret"] == "***"
    assert main(["--store", str(tmp / "store.json"), "--json", "publish", "nope", str(tmp / "missing.mp4")]) == 2
    assert json.loads(capsys.readouterr().out)["error"] == "ConfigError"


def test_interactive_connect_receives_callback(env) -> None:
    import threading
    from urllib.request import urlopen

    pub, *_ = env
    result: dict = {}

    def open_callback(url: str) -> None:
        state = dict(urllib.parse.parse_qsl(urllib.parse.urlparse(url).query))["state"]

        def hit() -> None:  # как будто TikTok вернул браузер на redirect_uri
            urlopen(f"http://127.0.0.1:38471/callback/?code=c0de&scopes=video.publish&state={state}").read()
        threading.Timer(0.2, hit).start()

    acc = pub.connect_interactive("main", port=38471, open_browser=False, timeout=10, on_url=open_callback)
    assert acc.name == "main" and acc.username == "chess_tv"
