"""Высокоуровневое API: подключить аккаунт и опубликовать видео.

    pub = Publisher()                                   # хранилище по умолчанию или TIKTOK_PUBLISHER_STORE
    pub.publish("main", "video.mp4", PostOptions(title="Подпись #тег"))

Токены продлеваются сами (доступа — 24 ч, обновления — 365 дней). Креды живут в хранилище модуля, а видео,
подпись и настройки поста передаёт приложение.
"""

from __future__ import annotations

import secrets
import threading
import time
import webbrowser
from dataclasses import asdict, dataclass, field
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Callable, Literal
from urllib.parse import parse_qs, urlparse

from tiktok_publisher.client import MAX_FILE, TikTokClient, chunk_plan
from tiktok_publisher.errors import ConfigError, PostingRestricted, PrivacyNotAllowed, TikTokError, UploadError
from tiktok_publisher.oauth import authorize_url, new_pkce
from tiktok_publisher.store import PRIVACY_LEVELS, Account, AccountStore

REFRESH_MARGIN = 5 * 60  # продлеваем токен доступа, если до конца меньше пяти минут
TITLE_LIMIT = 2200  # символов UTF-16
DONE = {"PUBLISH_COMPLETE", "SEND_TO_USER_INBOX", "FAILED"}


@dataclass
class PostOptions:
    """Всё о посте, кроме самого файла. Передаёт приложение."""
    title: str = ""  # подпись с хэштегами и упоминаниями, до 2200 символов
    privacy: str | None = None  # PUBLIC_TO_EVERYONE | MUTUAL_FOLLOW_FRIENDS | FOLLOWER_OF_CREATOR | SELF_ONLY; None — по аккаунту
    mode: Literal["direct", "inbox"] = "direct"  # direct — сразу в профиль, inbox — в черновики приложения TikTok
    disable_comment: bool = False
    disable_duet: bool = False
    disable_stitch: bool = False
    cover_timestamp_ms: int | None = None  # кадр обложки
    brand_content: bool = False  # платная реклама стороннего бренда
    brand_organic: bool = False  # продвижение собственного бизнеса
    is_aigc: bool = False  # пометка «создано ИИ»
    private_if_unaudited: bool = True  # пока приложение не прошло аудит TikTok — публиковать как SELF_ONLY, а не падать
    duration_sec: float | None = None  # если известна — проверяется по лимиту аккаунта


@dataclass
class PublishResult:
    account: str
    publish_id: str
    status: str  # PROCESSING_UPLOAD | SEND_TO_USER_INBOX | PUBLISH_COMPLETE | FAILED | …
    mode: str = "direct"
    privacy: str | None = None  # с какой приватностью ушёл пост
    post_ids: list[str] = field(default_factory=list)
    url: str | None = None  # ссылка на пост, когда TikTok её отдал (после модерации, для публичных)
    fail_reason: str | None = None
    note: str | None = None  # например, «опубликовано приватно: приложение не прошло аудит»

    @property
    def ok(self) -> bool:
        """Не провалилось: опубликовано, ушло в черновики или ещё обрабатывается."""
        return self.status != "FAILED" and not self.fail_reason

    def to_dict(self) -> dict:
        return {**asdict(self), "ok": self.ok}


class Publisher:
    def __init__(self, store: AccountStore | str | Path | None = None, client: TikTokClient | None = None,
                 clock: Callable[[], float] = time.time, sleep: Callable[[float], None] = time.sleep) -> None:
        self.store: AccountStore = store if isinstance(store, AccountStore) else AccountStore(store)
        self.client = client or TikTokClient()
        self.clock = clock
        self.sleep = sleep

    # ---------- подключение аккаунта ----------

    def start_connect(self, account: str, app: str = "default", redirect_uri: str | None = None,
                      scopes: list[str] | None = None) -> str:
        """Ссылка на вход в TikTok. Пользователь открывает её в браузере на той же машине."""
        a = self.store.get_app(app)
        redirect = redirect_uri or a.redirect_uri
        if not redirect:
            raise ConfigError("redirect_uri is not set for this app")
        verifier, challenge = new_pkce()
        state = secrets.token_urlsafe(24)
        self.store.add_pending(state, {"app": app, "account": account, "redirect_uri": redirect,
                                       "code_verifier": verifier})
        return authorize_url(a.client_key, redirect, scopes or a.scopes, state, challenge)

    def finish_connect(self, state: str, code: str) -> Account:
        """Обменять код из ответа TikTok на токены и сохранить аккаунт."""
        info = self.store.pop_pending(state)
        a = self.store.get_app(info["app"])
        tokens = self.client.token({
            "client_key": a.client_key, "client_secret": a.client_secret, "code": code,
            "grant_type": "authorization_code", "redirect_uri": info["redirect_uri"],
            "code_verifier": info["code_verifier"]})
        now = self.clock()
        try:
            old = self.store.get_account(info["account"])
            privacy = old.default_privacy
        except ConfigError:
            privacy = "SELF_ONLY"
        acc = Account(
            name=info["account"], app=info["app"], open_id=tokens.get("open_id", ""),
            access_token=tokens["access_token"], access_expires_at=now + int(tokens.get("expires_in", 86400)),
            refresh_token=tokens.get("refresh_token", ""),
            refresh_expires_at=now + int(tokens.get("refresh_expires_in", 365 * 86400)),
            scopes=[s for s in str(tokens.get("scope", "")).split(",") if s], default_privacy=privacy, connected_at=now)
        try:
            creator = self.client.creator_info(acc.access_token)
            acc.username = creator.get("creator_username", "")
            acc.display_name = creator.get("creator_nickname", "")
        except TikTokError:
            pass  # без video.publish сведений об авторе нет — аккаунт всё равно сохраняем
        self.store.save_account(acc)
        return acc

    def connect_interactive(self, account: str, app: str = "default", port: int = 3455, host: str = "127.0.0.1",
                            path: str = "/callback/", open_browser: bool = True, timeout: float = 300,
                            on_url: Callable[[str], None] | None = None) -> Account:
        """Подключить аккаунт с этой машины: открыть вход TikTok и принять ответ на http://host:port/path."""
        redirect = f"http://{host}:{port}{path}"
        url = self.start_connect(account, app, redirect)
        got: dict[str, str] = {}
        done = threading.Event()

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # noqa: N802
                q = {k: v[0] for k, v in parse_qs(urlparse(self.path).query).items()}
                if urlparse(self.path).path != path:
                    self.send_response(404)
                    self.end_headers()
                    return
                got.update(q)
                ok = "code" in q
                body = ("TikTok account connected. You can close this tab." if ok
                        else f"TikTok authorization failed: {q.get('error_description') or q.get('error')}")
                self.send_response(200)
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.end_headers()
                self.wfile.write(body.encode())
                done.set()

            def log_message(self, format: str, *args: object) -> None:  # noqa: A002 — тихо, без вывода в консоль
                pass

        server = HTTPServer((host, port), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            (on_url or (lambda u: None))(url)
            if open_browser:
                webbrowser.open(url)
            if not done.wait(timeout):
                raise ConfigError("timed out waiting for the TikTok authorization")
        finally:
            server.shutdown()
            server.server_close()
        if "code" not in got:
            raise ConfigError(f"authorization failed: {got.get('error_description') or got.get('error')}")
        return self.finish_connect(got.get("state", ""), got["code"])

    def disconnect(self, account: str, revoke: bool = True) -> None:
        acc = self.store.get_account(account)
        if revoke:
            try:
                a = self.store.get_app(acc.app)
                self.client.revoke(a.client_key, a.client_secret, acc.access_token)
            except TikTokError:
                pass
        self.store.remove_account(account)

    # ---------- токены ----------

    def access_token(self, account: str) -> str:
        """Действующий токен доступа; при необходимости продлевает его и сохраняет новые токены."""
        acc = self.store.get_account(account)
        now = self.clock()
        if acc.access_expires_at - now > REFRESH_MARGIN:
            return acc.access_token
        if acc.refresh_expires_at <= now:
            raise TikTokError("refresh token expired; connect the account again", code="refresh_expired")
        a = self.store.get_app(acc.app)
        tokens = self.client.token({"client_key": a.client_key, "client_secret": a.client_secret,
                                    "grant_type": "refresh_token", "refresh_token": acc.refresh_token})
        acc.access_token = tokens["access_token"]
        acc.access_expires_at = now + int(tokens.get("expires_in", 86400))
        if tokens.get("refresh_token"):  # TikTok может выдать новый refresh_token — старый тогда не годится
            acc.refresh_token = tokens["refresh_token"]
            acc.refresh_expires_at = now + int(tokens.get("refresh_expires_in", 365 * 86400))
        self.store.save_account(acc)
        return acc.access_token

    def creator_info(self, account: str) -> dict:
        return self.client.creator_info(self.access_token(account))

    # ---------- публикация ----------

    def publish(self, account: str, video: str | Path, options: PostOptions | None = None, wait: bool = True,
                timeout: float = 600, poll_interval: float = 5) -> PublishResult:
        """Опубликовать видео. wait=True — дождаться, пока TikTok обработает файл (или выйдет timeout)."""
        opts = options or PostOptions()
        video = Path(video)
        if not video.is_file():
            raise ConfigError(f"video not found: {video}")
        if video.stat().st_size > MAX_FILE:
            raise UploadError("video is larger than 4 GB")
        if len(opts.title.encode("utf-16-le")) // 2 > TITLE_LIMIT:
            raise ConfigError(f"title is longer than {TITLE_LIMIT} characters")
        acc = self.store.get_account(account)
        token = self.access_token(account)
        size = video.stat().st_size
        chunk_size, chunks = chunk_plan(size)
        source = {"source": "FILE_UPLOAD", "video_size": size, "chunk_size": chunk_size, "total_chunk_count": chunks}

        privacy, note = None, None
        if opts.mode == "inbox":
            init = self.client.init_video(token, None, source, inbox=True)
        else:
            creator = self.client.creator_info(token)  # обязателен по правилам TikTok перед каждым постом
            limit = creator.get("max_video_post_duration_sec")
            if opts.duration_sec and limit and opts.duration_sec > limit:
                raise ConfigError(f"video is {opts.duration_sec:.0f}s, the account allows up to {limit}s")
            privacy = opts.privacy or acc.default_privacy
            allowed: list[str] = list(creator.get("privacy_level_options") or PRIVACY_LEVELS)
            if privacy not in allowed:
                raise PrivacyNotAllowed(f"privacy {privacy} is not available for this account", allowed=allowed)
            post = {
                "title": opts.title, "privacy_level": privacy,
                "disable_comment": opts.disable_comment or bool(creator.get("comment_disabled")),
                "disable_duet": opts.disable_duet or bool(creator.get("duet_disabled")),
                "disable_stitch": opts.disable_stitch or bool(creator.get("stitch_disabled")),
                "brand_content_toggle": opts.brand_content, "brand_organic_toggle": opts.brand_organic,
                "is_aigc": opts.is_aigc,
            }
            if opts.cover_timestamp_ms is not None:
                post["video_cover_timestamp_ms"] = opts.cover_timestamp_ms
            try:
                init = self.client.init_video(token, post, source)
            except PostingRestricted as e:
                if e.code != "unaudited_client_can_only_post_to_private_accounts" or not opts.private_if_unaudited \
                        or privacy == "SELF_ONLY":
                    raise
                privacy, note = "SELF_ONLY", "published privately: the TikTok app has not passed the audit yet"
                init = self.client.init_video(token, {**post, "privacy_level": privacy}, source)

        publish_id = init["publish_id"]
        self.client.upload(init["upload_url"], video, chunk_size, chunks)
        result = PublishResult(account=account, publish_id=publish_id, status="PROCESSING_UPLOAD", mode=opts.mode,
                               privacy=privacy, note=note)
        if not wait:
            return result
        deadline = self.clock() + timeout
        while True:
            result = self.status(account, publish_id, mode=opts.mode, privacy=privacy, note=note)
            if result.status in DONE or self.clock() >= deadline:
                return result
            self.sleep(poll_interval)

    def status(self, account: str, publish_id: str, mode: str = "direct", privacy: str | None = None,
               note: str | None = None) -> PublishResult:
        data = self.client.status(self.access_token(account), publish_id)
        ids = [str(x) for x in (data.get("publicaly_available_post_id") or data.get("publicly_available_post_id") or [])]
        username = self.store.get_account(account).username
        url = f"https://www.tiktok.com/@{username}/video/{ids[0]}" if ids and username else None
        return PublishResult(account=account, publish_id=publish_id, status=data.get("status", "UNKNOWN"), mode=mode,
                             privacy=privacy, post_ids=ids, url=url, fail_reason=data.get("fail_reason") or None,
                             note=note)
