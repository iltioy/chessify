# tiktok-publisher

**English** · [Русский](README.ru.md)

A small, dependency-free Python module that publishes videos to TikTok accounts through the **official
TikTok Content Posting API**. It keeps the credentials of several TikTok apps and accounts in one store,
so different services can post to different accounts. Everything about the post itself — the video file,
the caption, privacy and so on — is passed in by the calling application.

- Multi-account token store (JSON, `0600`, file lock, optional encryption).
- OAuth 2.0 sign-in with PKCE for apps without a public HTTPS address (loopback redirect).
- Automatic token refresh (access token — 24 h, refresh token — 365 days, rotated refresh tokens are saved).
- Direct posting to the profile or upload to the account's drafts (inbox).
- Chunked upload, status polling, link to the published post.
- Python API and a CLI with JSON output — usable from any language.
- For agents integrating it into a project: [INTEGRATION.md](INTEGRATION.md).

## Why not a login and password

TikTok has no way to publish with a login and password, and automating the sign-in page breaks TikTok's
terms and gets accounts banned. The module uses the official API: you register your own app on TikTok
for Developers (that gives a **client key** and **client secret**), and each TikTok account is connected
once through TikTok's own sign-in page. The module stores the resulting **tokens**, never passwords.

## Limits set by TikTok

- **Until your app passes TikTok's audit, every post is private** (visible only to the account owner).
  By default the module then posts privately instead of failing and reports it in `PublishResult.note`.
  Alternatively, use the `inbox` mode: the video lands in the account's drafts and the owner publishes it
  from the TikTok app in one tap.
- Video: MP4 (recommended), MOV or WebM; H.264/H.265/VP8/VP9; up to 4 GB; 23–60 FPS; 360–4096 px per side;
  up to 10 minutes (and up to the account's own limit).
- Caption: up to 2200 characters.
- Rate limits: 6 post requests per minute per account; TikTok also caps posts per day and, for drafts,
  5 pending uploads per 24 hours.

## 1. Register a TikTok app (once)

1. Sign in at [developers.tiktok.com](https://developers.tiktok.com/) → **Manage apps** → **Connect an app**.
2. Platform: **Desktop** — it allows `http://127.0.0.1:<port>/…` redirect addresses, so no public HTTPS site is needed.
3. Add the products **Login Kit** and **Content Posting API** (enable **Direct Post**).
4. Scopes: `user.info.basic`, `video.publish`, and `video.upload` if you want the drafts mode.
5. In Login Kit, add redirect URIs. For the CLI: `http://127.0.0.1:*/callback/`. For an app with its own
   callback, add its address too (e.g. `http://127.0.0.1:*/api/tiktok/callback/`).
6. Copy the **Client key** and **Client secret**.
7. While the app is in development, TikTok may only let the accounts you add as testers sign in.
   To post publicly, submit the app for review (audit).

## 2. Install

Python 3.10+, no dependencies.

```bash
pip install ./modules/tiktok-publisher                      # from a checkout
pip install "tiktok-publisher @ git+https://github.com/<you>/<repo>#subdirectory=modules/tiktok-publisher"
pip install "./modules/tiktok-publisher[crypto]"            # + encrypted store
```

## 3. Store

One JSON file with apps, accounts and their tokens. Location: `--store` / constructor argument,
otherwise `TIKTOK_PUBLISHER_STORE`, otherwise `~/.config/tiktok-publisher/store.json`.

- It holds secrets: keep it out of git and backups you share; the module writes it with `0600` permissions.
- Encryption: install the `crypto` extra and set `TIKTOK_PUBLISHER_KEY` to a Fernet key
  (`python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`).
- Several services can share one store and use different account names, or each can have its own store.

## 4. Command line

```bash
tiktok-publisher app add default --client-key <KEY>                 # asks for the secret
tiktok-publisher account connect main --app default                 # opens TikTok sign-in in the browser
tiktok-publisher account set main --privacy PUBLIC_TO_EVERYONE      # default privacy of the account
tiktok-publisher account list
tiktok-publisher info main                                          # nickname, allowed privacy, max duration
tiktok-publisher publish main video.mp4 --title "A chess game #chess" --json
tiktok-publisher publish main video.mp4 --mode inbox                # to the drafts instead
tiktok-publisher status main <publish_id>
```

With `--json`, every command prints JSON; exit code 0 — success, 1 — TikTok reported a failure, 2 — error.

## 5. Python

```python
from tiktok_publisher import Publisher, PostOptions, AuthError

pub = Publisher("/path/to/store.json")
result = pub.publish("main", "out/video.mp4", PostOptions(
    title="Mike vs the DEA: an interrogation as a chess game #breakingbad",
    privacy=None,            # None — the account's default privacy
    mode="direct",           # or "inbox"
    is_aigc=False,
))
print(result.status, result.privacy, result.url, result.note)
```

Connecting an account from your own web app: `url = pub.start_connect("main", app="default",
redirect_uri="http://127.0.0.1:8080/tiktok/callback/")` → send the user to `url` → on the callback call
`pub.finish_connect(state, code)`. Details and the error-handling contract are in [INTEGRATION.md](INTEGRATION.md).

## Errors

All errors derive from `TikTokError` (`code`, `http_status`, `log_id`):
`AuthError` (reconnect the account), `RateLimitError` (retry later), `PostingRestricted` (TikTok refuses:
daily cap, ban, unaudited app), `PrivacyNotAllowed` (`.allowed` lists what is allowed), `UploadError`,
`ConfigError` (unknown app/account, bad options).

## Tests

```bash
python -m pytest tests     # a fake TikTok, no network
```
