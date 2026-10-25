"""tiktok-publisher: публикация видео в аккаунты TikTok через официальный Content Posting API.

Публичное API:
    Publisher, PostOptions, PublishResult — подключение аккаунтов и публикация;
    AccountStore, App, Account — хранилище приложений и аккаунтов;
    ошибки — TikTokError и подклассы.
Подробности — README.md, порядок встраивания в проект — INTEGRATION.md.
"""

from tiktok_publisher.errors import (AuthError, ConfigError, PostingRestricted, PrivacyNotAllowed, RateLimitError,
                                     TikTokError, UploadError)
from tiktok_publisher.publisher import PostOptions, Publisher, PublishResult
from tiktok_publisher.store import PRIVACY_LEVELS, Account, AccountStore, App

__version__ = "0.1.0"
__all__ = ["Account", "AccountStore", "App", "AuthError", "ConfigError", "PRIVACY_LEVELS", "PostOptions",
           "PostingRestricted", "PrivacyNotAllowed", "PublishResult", "Publisher", "RateLimitError", "TikTokError",
           "UploadError"]
