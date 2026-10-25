# tiktok-publisher

[English](README.md) · **Русский**

Небольшой модуль на Python без зависимостей: публикует видео в аккаунты TikTok через **официальный
Content Posting API**. Хранит креды нескольких приложений и аккаунтов TikTok в одном хранилище — разные
сервисы публикуют в разные аккаунты. Всё о самом посте — файл, подпись, приватность — передаёт приложение.

- Хранилище токенов нескольких аккаунтов (JSON, права 0600, блокировка, по желанию — шифрование).
- Вход OAuth 2.0 с PKCE для программ без публичного https-адреса (возврат на 127.0.0.1).
- Токены продлеваются сами (доступа — 24 ч, обновления — 365 дней), новый refresh-токен сохраняется.
- Публикация сразу в профиль или загрузка в черновики аккаунта.
- Загрузка частями, ожидание статуса, ссылка на пост.
- Python API и командная строка с JSON — подходит для проектов на любом языке.
- Агенту, который встраивает модуль в проект: [INTEGRATION.md](INTEGRATION.md).

## Почему не логин и пароль

Публиковать по логину и паролю TikTok не позволяет, а автоматизация страницы входа нарушает правила TikTok
и приводит к блокировке аккаунтов. Модуль работает через официальный API: вы регистрируете своё приложение
на TikTok for Developers (получаете **client key** и **client secret**), а каждый аккаунт TikTok один раз
подключается через страницу входа TikTok. Модуль хранит выданные **токены**, пароли — никогда.

## Ограничения TikTok

- **Пока приложение не прошло аудит TikTok, все посты приватные** (видит только владелец). По умолчанию модуль
  тогда публикует приватно, а не падает, и сообщает об этом в `PublishResult.note`. Другой вариант — режим
  `inbox`: видео попадает в черновики аккаунта, и владелец публикует его из приложения TikTok одним нажатием.
- Видео: MP4 (лучше), MOV или WebM; H.264/H.265/VP8/VP9; до 4 ГБ; 23–60 к/с; 360–4096 px по сторонам;
  до 10 минут (и до лимита самого аккаунта).
- Подпись — до 2200 символов.
- Лимиты: 6 запросов на публикацию в минуту на аккаунт; TikTok ограничивает и число постов в день,
  а для черновиков — 5 ожидающих загрузок за сутки.

## 1. Зарегистрировать приложение TikTok (один раз)

1. Войдите на [developers.tiktok.com](https://developers.tiktok.com/) → **Manage apps** → **Connect an app**.
2. Платформа: **Desktop** — она разрешает адреса возврата `http://127.0.0.1:<порт>/…`, публичный https-сайт не нужен.
3. Добавьте продукты **Login Kit** и **Content Posting API** (включите **Direct Post**).
4. Разрешения: `user.info.basic`, `video.publish` и `video.upload`, если нужен режим черновиков.
5. В Login Kit добавьте адреса возврата. Для командной строки: `http://127.0.0.1:*/callback/`. Для приложения
   со своим адресом — и его (например, `http://127.0.0.1:*/api/tiktok/callback/`).
6. Скопируйте **Client key** и **Client secret**.
7. Пока приложение в разработке, TikTok может пускать только аккаунты, добавленные как тестировщики.
   Для публичных постов отправьте приложение на проверку (аудит).

## 2. Установка

Python 3.10+, без зависимостей.

```bash
pip install ./modules/tiktok-publisher                      # из копии репозитория
pip install "tiktok-publisher @ git+https://github.com/<вы>/<репозиторий>#subdirectory=modules/tiktok-publisher"
pip install "./modules/tiktok-publisher[crypto]"            # + шифрование хранилища
```

## 3. Хранилище

Один JSON-файл с приложениями, аккаунтами и их токенами. Путь: `--store` / аргумент конструктора,
иначе `TIKTOK_PUBLISHER_STORE`, иначе `~/.config/tiktok-publisher/store.json`.

- В нём секреты: держите его вне git и общих резервных копий; модуль пишет его с правами 0600.
- Шифрование: поставьте вариант `crypto` и задайте в `TIKTOK_PUBLISHER_KEY` ключ Fernet
  (`python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`).
- Несколько сервисов могут делить одно хранилище под разными именами аккаунтов или иметь каждый своё.

## 4. Командная строка

```bash
tiktok-publisher app add default --client-key <KEY>                 # секрет спросит сам
tiktok-publisher account connect main --app default                 # откроет вход TikTok в браузере
tiktok-publisher account set main --privacy PUBLIC_TO_EVERYONE      # приватность аккаунта по умолчанию
tiktok-publisher account list
tiktok-publisher info main                                          # имя, доступная приватность, лимит длительности
tiktok-publisher publish main video.mp4 --title "Шахматная партия #шахматы" --json
tiktok-publisher publish main video.mp4 --mode inbox                # в черновики
tiktok-publisher status main <publish_id>
```

С `--json` каждая команда печатает JSON; код выхода 0 — успех, 1 — TikTok сообщил о сбое, 2 — ошибка.

## 5. Python

```python
from tiktok_publisher import Publisher, PostOptions

pub = Publisher("/путь/к/store.json")
result = pub.publish("main", "out/video.mp4", PostOptions(
    title="Майк против DEA: допрос как шахматная партия #вовсетяжкие",
    privacy=None,            # None — приватность аккаунта по умолчанию
    mode="direct",           # или "inbox"
))
print(result.status, result.privacy, result.url, result.note)
```

Подключение аккаунта из своего веб-приложения: `url = pub.start_connect("main", app="default",
redirect_uri="http://127.0.0.1:8080/tiktok/callback/")` → отправить пользователя по `url` → в обработчике
возврата вызвать `pub.finish_connect(state, code)`. Подробности и разбор ошибок — в [INTEGRATION.md](INTEGRATION.md).

## Ошибки

Все ошибки наследуют `TikTokError` (`code`, `http_status`, `log_id`): `AuthError` (подключить аккаунт заново),
`RateLimitError` (повторить позже), `PostingRestricted` (TikTok отказал: лимит, бан, приложение без аудита),
`PrivacyNotAllowed` (в `.allowed` — что можно), `UploadError`, `ConfigError` (нет приложения/аккаунта, неверные параметры).

## Тесты

```bash
python -m pytest tests     # поддельный TikTok, без сети
```
