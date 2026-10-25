"""Ошибки модуля. Код ошибки TikTok сохраняется в `code`, идентификатор запроса — в `log_id`."""

from __future__ import annotations


class TikTokError(Exception):
    """Любая ошибка TikTok API или модуля."""

    def __init__(self, message: str, *, code: str = "", http_status: int | None = None, log_id: str = "") -> None:
        super().__init__(message)
        self.code = code
        self.http_status = http_status
        self.log_id = log_id

    def __str__(self) -> str:
        extra = ", ".join(x for x in (self.code, f"log_id={self.log_id}" if self.log_id else "") if x)
        return f"{super().__str__()} ({extra})" if extra else super().__str__()


class ConfigError(TikTokError):
    """Нет такого приложения или аккаунта, неверные параметры."""


class AuthError(TikTokError):
    """Токен недействителен, отозван или без нужного разрешения — аккаунт нужно подключить заново."""


class RateLimitError(TikTokError):
    """Слишком много запросов: повторить позже."""


class PostingRestricted(TikTokError):
    """TikTok не даёт публиковать: лимит постов, бан, неаудированное приложение и т. п."""


class PrivacyNotAllowed(TikTokError):
    """Выбранная приватность недоступна этому аккаунту."""

    def __init__(self, message: str, *, allowed: list[str], **kw) -> None:
        super().__init__(message, **kw)
        self.allowed = allowed


class UploadError(TikTokError):
    """Файл не загрузился или TikTok отклонил его при обработке."""


AUTH_CODES = {"access_token_invalid", "scope_not_authorized", "invalid_grant", "invalid_token", "auth_removed"}
RESTRICTED_CODES = {"spam_risk_too_many_posts", "spam_risk_user_banned_from_posting", "reached_active_user_cap",
                    "unaudited_client_can_only_post_to_private_accounts", "spam_risk_too_many_pending_share",
                    "url_ownership_unverified", "spam_risk_text", "spam_risk"}


def from_code(code: str, message: str, *, http_status: int | None = None, log_id: str = "") -> TikTokError:
    """Ошибка нужного класса по коду TikTok."""
    kw = {"code": code, "http_status": http_status, "log_id": log_id}
    if code in AUTH_CODES or http_status == 401:
        return AuthError(message, **kw)
    if code == "rate_limit_exceeded" or http_status == 429:
        return RateLimitError(message, **kw)
    if code == "privacy_level_option_mismatch":
        return PrivacyNotAllowed(message, allowed=[], **kw)
    if code in RESTRICTED_CODES:
        return PostingRestricted(message, **kw)
    return TikTokError(message, **kw)
