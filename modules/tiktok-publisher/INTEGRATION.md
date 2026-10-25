# Integrating tiktok-publisher into a project (for agents)

This document tells an agent how to add automatic TikTok publishing to an application that produces videos.
Read [README.md](README.md) first for what the module does and how a TikTok app is registered.
The reference integration is Chessify (`src/chessify/tiktok.py`, `src/chessify/web/app.py` — `/api/tiktok/*`).

## Contract

| Owned by the module | Owned by the application |
|---|---|
| TikTok app credentials (client key/secret, redirect URI, scopes) | which **account name** it publishes to |
| account tokens, their refresh and rotation | the **video file** (final, on local disk) |
| OAuth state + PKCE verifier between start and finish | **caption**, privacy, comment/duet/stitch, AIGC/brand flags |
| TikTok API calls, chunked upload, status polling | when to publish, where to store the result, what to show the user |

Never move credentials into the application's own config, never pass tokens around: the application only
knows account **names** (e.g. `"main"`, `"brand-ru"`). One store can serve several services, each using its
own account names, or every service can have its own store file.

## Steps

### 1. Add the dependency

Pick one, in order of preference:

1. **Package dependency** — `tiktok-publisher` from a path or a git subdirectory
   (`tiktok-publisher @ git+https://…#subdirectory=modules/tiktok-publisher`). It has no dependencies.
2. **Vendored copy** — copy `modules/tiktok-publisher/` into the project and import it via a small shim that
   falls back to `sys.path` (see `src/chessify/tiktok.py`). Use this when changing the project's lock file is
   expensive (e.g. it would rebuild a heavy Docker layer).

Keep the module unmodified; project-specific behaviour belongs in the project's own wrapper.

### 2. Choose the store location

- Pass an explicit path (`Publisher(path)`) inside the project's **private data/settings directory**,
  or rely on `TIKTOK_PUBLISHER_STORE`. Never inside the repository: add it to `.gitignore`/`.dockerignore`.
- In Docker, put it on a mounted volume so tokens survive container rebuilds.
- Optional encryption: `cryptography` installed + `TIKTOK_PUBLISHER_KEY` (Fernet key) in the environment.

### 3. Credentials and accounts

- Save the TikTok app: `AccountStore(path).set_app(App(name, client_key, client_secret, redirect_uri, scopes))`.
  If the project has a settings UI, write to the module store from there — never return the secret to the client.
- Connect an account, one of:
  - **CLI/headless**: `Publisher.connect_interactive(name, app)` — starts a loopback server on
    `http://127.0.0.1:<port>/callback/` and opens the browser. The URI (with `*` port) must be registered in Login Kit.
  - **Web app**: `url = pub.start_connect(name, app, redirect_uri)` → redirect the user to `url` →
    in your callback handler `pub.finish_connect(request.query["state"], request.query["code"])`.
    TikTok allows only `127.0.0.1`/`localhost` redirect hosts for Desktop apps, so the user must open
    the app on the same machine; build `redirect_uri` from the request's port and keep its path static.
    Handle `error`/`error_description` in the callback query.
- Show accounts with `Account.public()` (no tokens). Let the user set a default privacy
  (`AccountStore.set_default_privacy`).

### 4. Publish after the video is final

- Call `Publisher.publish(account, video_path, PostOptions(...))` **in a background job**, not in a request
  handler: uploading and processing take from seconds to minutes. `wait=True` (default) polls until TikTok
  finishes or `timeout` passes; with `wait=False`, store `publish_id` and poll `Publisher.status()` later
  (≤ 30 requests/min).
- `PostOptions.privacy=None` uses the account default. `private_if_unaudited=True` (default) posts as
  `SELF_ONLY` while the TikTok app is unaudited and explains it in `result.note` — surface that note to the user.
- `mode="inbox"` sends the video to the account's drafts instead (needs the `video.upload` scope).
- Pass `duration_sec` if you know it — it is checked against the account's maximum.
- Caption: ≤ 2200 characters, hashtags and `@mentions` inline. Generate a default from the project's data, let
  the user edit it.
- Publishing must never fail the main job: the video already exists. Record the publishing result separately.

### 5. Store and show the result

Persist `PublishResult.to_dict()` with the job: `publish_id`, `status`, `privacy`, `url` (may be `None` until
TikTok finishes moderation, and stays `None` for private posts), `fail_reason`, `note`, `ok`.

### 6. Handle errors

| Exception | Meaning | What to do |
|---|---|---|
| `AuthError` | token invalid/revoked, scope missing | mark the account as needing reconnection; don't retry |
| `RateLimitError` | too many requests | retry with backoff (≥ 10 s; 6 init requests/min per account) |
| `PostingRestricted` | daily cap, ban, unaudited app, spam risk | show `str(e)` / `e.code`; don't retry automatically |
| `PrivacyNotAllowed` | chosen privacy not allowed | show `e.allowed`, let the user pick |
| `UploadError` | upload failed / video rejected by checks | retry once; on repeat show the message |
| `ConfigError` | unknown app/account, bad options, expired OAuth state | fix configuration; don't retry |
| `TikTokError` | anything else (5xx, network) | retry later |

`FAILED` status with `fail_reason` (e.g. `duration_check_failed`, `spam_risk_text`) comes back in the result,
not as an exception.

### 7. Test

Inject a fake transport — no network, no TikTok account:

```python
from tiktok_publisher import Publisher, AccountStore
from tiktok_publisher.client import TikTokClient

pub = Publisher(AccountStore(tmp_path / "store.json"), TikTokClient(FakeTransport()), sleep=lambda s: None)
```

`FakeTransport.request(method, url, headers, body, timeout)` returns `(status, headers, body)`;
a complete example is in `tests/test_publisher.py`. In the application's own tests, stub
`Publisher.publish` and assert what is passed and how the result is stored.

## Checklist

- [ ] Dependency added (package or vendored copy + shim); module code unchanged.
- [ ] Store path outside the repo, ignored by git/docker, on persistent storage.
- [ ] App credentials saved through the module; the secret is never sent back to a client or logged.
- [ ] Account connection flow works; its redirect URI is registered in TikTok Login Kit.
- [ ] Publishing runs in the background after the final video exists, with a user-editable caption.
- [ ] The result (status, privacy, URL, note) is stored and shown; errors are handled per the table.
- [ ] Tests with a fake transport or a stubbed `Publisher`.
- [ ] The user is told that until TikTok's audit, posts are private (or uses the drafts mode).

## Don't

- Don't ask for or store TikTok logins/passwords, and don't automate the TikTok website.
- Don't log tokens or the client secret; `Account.public()` is the safe representation.
- Don't call the post endpoints in a tight loop; respect the rate limits and daily caps.
- Don't try to bypass the audit restriction; private posting or drafts are the supported paths.
- The application is responsible for having the rights to the content it publishes.
