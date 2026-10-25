"""Низкоуровневый клиент TikTok API: OAuth-токены, сведения об авторе, публикация, загрузка, статус.

Только стандартная библиотека. Транспорт подменяется (тесты, прокси): объект с методом
`request(method, url, headers, body, timeout) -> (status, headers, body)`.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Protocol

from tiktok_publisher.errors import TikTokError, UploadError, from_code

API = "https://open.tiktokapis.com"
AUTHORIZE_URL = "https://www.tiktok.com/v2/auth/authorize/"

MIN_CHUNK = 5 * 1024 * 1024  # меньше — файл целиком
MAX_SINGLE = 64 * 1024 * 1024  # больше — только частями
CHUNK = 32 * 1024 * 1024  # части по 32 МБ (допустимо 5–64 МБ, последняя — до 128 МБ)
MAX_FILE = 4 * 1024 ** 3
CONTENT_TYPES = {".mp4": "video/mp4", ".mov": "video/quicktime", ".webm": "video/webm"}


class Transport(Protocol):
    def request(self, method: str, url: str, headers: dict[str, str], body: bytes | None,
                timeout: float) -> tuple[int, dict[str, str], bytes]: ...


class UrllibTransport:
    def request(self, method: str, url: str, headers: dict[str, str], body: bytes | None,
                timeout: float) -> tuple[int, dict[str, str], bytes]:
        req = urllib.request.Request(url, data=body, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 — только https API TikTok
                return resp.status, dict(resp.headers), resp.read()
        except urllib.error.HTTPError as e:
            return e.code, dict(e.headers or {}), e.read() or b""
        except urllib.error.URLError as e:
            raise TikTokError(f"network error: {e.reason}") from e


def chunk_plan(size: int) -> tuple[int, int]:
    """(chunk_size, total_chunk_count) по правилам TikTok: последняя часть забирает остаток."""
    if size <= 0:
        raise UploadError("empty video file")
    if size > MAX_FILE:
        raise UploadError("video is larger than 4 GB")
    if size <= MAX_SINGLE:
        return size, 1
    return CHUNK, size // CHUNK


class TikTokClient:
    def __init__(self, transport: Transport | None = None, timeout: float = 60) -> None:
        self.transport = transport or UrllibTransport()
        self.timeout = timeout

    # ---------- OAuth ----------

    def token(self, form: dict[str, str]) -> dict:
        """POST /v2/oauth/token/ — обмен кода или обновление токена."""
        body = urllib.parse.urlencode(form).encode()
        status, _, raw = self.transport.request(
            "POST", f"{API}/v2/oauth/token/",
            {"Content-Type": "application/x-www-form-urlencoded", "Cache-Control": "no-cache"}, body, self.timeout)
        data = _json(raw)
        if status != 200 or data.get("error") or "access_token" not in data:
            code = str(data.get("error") or data.get("error_code") or "token_error")
            raise from_code(code, str(data.get("error_description") or data.get("message") or "token request failed"),
                            http_status=status, log_id=str(data.get("log_id", "")))
        return data

    def revoke(self, client_key: str, client_secret: str, access_token: str) -> None:
        body = urllib.parse.urlencode({"client_key": client_key, "client_secret": client_secret,
                                       "token": access_token}).encode()
        self.transport.request("POST", f"{API}/v2/oauth/revoke/",
                               {"Content-Type": "application/x-www-form-urlencoded"}, body, self.timeout)

    # ---------- Content Posting API ----------

    def _post(self, access_token: str, path: str, payload: dict) -> dict:
        status, _, raw = self.transport.request(
            "POST", f"{API}{path}",
            {"Authorization": f"Bearer {access_token}", "Content-Type": "application/json; charset=UTF-8"},
            json.dumps(payload).encode(), self.timeout)
        data = _json(raw)
        err = data.get("error") or {}
        code = err.get("code", "ok" if status == 200 else "http_error")
        if code != "ok" or status >= 400:
            raise from_code(code, err.get("message") or f"HTTP {status}", http_status=status,
                            log_id=str(err.get("log_id") or err.get("logid") or ""))
        return data.get("data") or {}

    def creator_info(self, access_token: str) -> dict:
        """Аккаунт, куда уйдёт пост: имя, доступная приватность, лимит длительности."""
        return self._post(access_token, "/v2/post/publish/creator_info/query/", {})

    def init_video(self, access_token: str, post_info: dict | None, source_info: dict, inbox: bool = False) -> dict:
        """Начать публикацию (inbox=False) или загрузку в черновики (inbox=True)."""
        if inbox:
            return self._post(access_token, "/v2/post/publish/inbox/video/init/", {"source_info": source_info})
        return self._post(access_token, "/v2/post/publish/video/init/",
                          {"post_info": post_info or {}, "source_info": source_info})

    def upload(self, upload_url: str, video: Path, chunk_size: int, total_chunks: int) -> None:
        """PUT частями по порядку; ответ 206 — дальше, 201 — всё загружено."""
        size = video.stat().st_size
        content_type = CONTENT_TYPES.get(video.suffix.lower(), "video/mp4")
        with video.open("rb") as f:
            for i in range(total_chunks):
                start = i * chunk_size
                end = size - 1 if i == total_chunks - 1 else start + chunk_size - 1
                f.seek(start)
                part = f.read(end - start + 1)
                status, _, raw = self.transport.request(
                    "PUT", upload_url,
                    {"Content-Type": content_type, "Content-Length": str(len(part)),
                     "Content-Range": f"bytes {start}-{end}/{size}"}, part, max(self.timeout, 300))
                if status not in (200, 201, 206):
                    raise UploadError(f"chunk {i + 1}/{total_chunks} upload failed: HTTP {status} {raw[:200]!r}",
                                      http_status=status)

    def status(self, access_token: str, publish_id: str) -> dict:
        return self._post(access_token, "/v2/post/publish/status/fetch/", {"publish_id": publish_id})


def _json(raw: bytes) -> dict:
    try:
        data = json.loads(raw or b"{}")
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}
