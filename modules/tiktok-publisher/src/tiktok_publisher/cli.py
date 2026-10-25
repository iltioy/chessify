"""Командная строка: настройка приложений и аккаунтов, публикация. С --json вывод — JSON (для других языков).

    tiktok-publisher app add default --client-key KEY            # секрет спросит сам
    tiktok-publisher account connect main --app default          # откроет вход TikTok в браузере
    tiktok-publisher publish main video.mp4 --title "Подпись #тег" --json
"""

from __future__ import annotations

import argparse
import getpass
import json
import os
import sys
from dataclasses import asdict

from tiktok_publisher.errors import PrivacyNotAllowed, TikTokError
from tiktok_publisher.publisher import PostOptions, Publisher
from tiktok_publisher.store import DEFAULT_SCOPES, PRIVACY_LEVELS, AccountStore, App


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="tiktok-publisher", description="Publish videos to TikTok accounts.")
    p.add_argument("--store", help="store file (default: TIKTOK_PUBLISHER_STORE or ~/.config/tiktok-publisher/store.json)")
    p.add_argument("--json", action="store_true", help="print results as JSON")
    sub = p.add_subparsers(dest="cmd", required=True)

    app = sub.add_parser("app", help="TikTok developer apps (client key/secret)").add_subparsers(dest="action", required=True)
    add = app.add_parser("add", help="add or update an app")
    add.add_argument("name")
    add.add_argument("--client-key", required=True)
    add.add_argument("--client-secret", help="omit to be prompted (or set TIKTOK_CLIENT_SECRET)")
    add.add_argument("--redirect-uri", default="", help="registered redirect URI, e.g. http://127.0.0.1:3455/callback/")
    add.add_argument("--scopes", default=",".join(DEFAULT_SCOPES))
    app.add_parser("list", help="list apps")
    rm = app.add_parser("remove", help="remove an app")
    rm.add_argument("name")

    acc = sub.add_parser("account", help="connected TikTok accounts").add_subparsers(dest="action", required=True)
    con = acc.add_parser("connect", help="connect an account through the TikTok sign-in page")
    con.add_argument("name", help="your name for the account, e.g. main")
    con.add_argument("--app", default="default")
    con.add_argument("--port", type=int, default=3455)
    con.add_argument("--no-browser", action="store_true", help="only print the URL")
    acc.add_parser("list", help="list accounts")
    arm = acc.add_parser("remove", help="disconnect an account")
    arm.add_argument("name")
    arm.add_argument("--no-revoke", action="store_true")
    aset = acc.add_parser("set", help="change account settings")
    aset.add_argument("name")
    aset.add_argument("--privacy", choices=PRIVACY_LEVELS, required=True)

    info = sub.add_parser("info", help="creator info: username, allowed privacy levels, max duration")
    info.add_argument("account")

    pub = sub.add_parser("publish", help="publish a video")
    pub.add_argument("account")
    pub.add_argument("video")
    pub.add_argument("--title", default="", help="caption with hashtags")
    pub.add_argument("--privacy", choices=PRIVACY_LEVELS)
    pub.add_argument("--mode", choices=("direct", "inbox"), default="direct")
    pub.add_argument("--no-comment", action="store_true")
    pub.add_argument("--no-duet", action="store_true")
    pub.add_argument("--no-stitch", action="store_true")
    pub.add_argument("--aigc", action="store_true", help="label the post as AI-generated")
    pub.add_argument("--no-wait", action="store_true", help="don't wait for TikTok to process the video")
    pub.add_argument("--timeout", type=float, default=600)

    st = sub.add_parser("status", help="status of a publish_id")
    st.add_argument("account")
    st.add_argument("publish_id")
    return p


def _out(args, data, text: str) -> None:
    print(json.dumps(data, ensure_ascii=False, indent=1) if args.json else text)


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    store = AccountStore(args.store)
    pub = Publisher(store)
    try:
        if args.cmd == "app":
            if args.action == "add":
                secret = args.client_secret or os.environ.get("TIKTOK_CLIENT_SECRET") or getpass.getpass("Client secret: ")
                store.set_app(App(args.name, args.client_key, secret, args.redirect_uri,
                                  [s for s in args.scopes.split(",") if s]))
                _out(args, {"ok": True, "app": args.name}, f"app {args.name} saved")
            elif args.action == "list":
                apps = [{**asdict(a), "client_secret": "***"} for a in store.list_apps()]
                _out(args, apps, "\n".join(f"{a['name']}: {a['client_key']} {a['redirect_uri']}" for a in apps) or "no apps")
            else:
                store.remove_app(args.name)
                _out(args, {"ok": True}, f"app {args.name} removed")
        elif args.cmd == "account":
            if args.action == "connect":
                acc = pub.connect_interactive(args.name, args.app, port=args.port, open_browser=not args.no_browser,
                                              on_url=lambda u: print(f"Open this URL to sign in:\n{u}", file=sys.stderr))
                _out(args, acc.public(), f"account {acc.name} connected: @{acc.username or '?'}")
            elif args.action == "list":
                accs = [a.public() for a in store.list_accounts()]
                _out(args, accs, "\n".join(f"{a['name']}: @{a['username']} ({a['app']}, {a['default_privacy']})"
                                           for a in accs) or "no accounts")
            elif args.action == "remove":
                pub.disconnect(args.name, revoke=not args.no_revoke)
                _out(args, {"ok": True}, f"account {args.name} disconnected")
            else:
                store.set_default_privacy(args.name, args.privacy)
                _out(args, {"ok": True}, f"account {args.name}: default privacy {args.privacy}")
        elif args.cmd == "info":
            data = pub.creator_info(args.account)
            _out(args, data, json.dumps(data, ensure_ascii=False, indent=1))
        elif args.cmd == "publish":
            opts = PostOptions(title=args.title, privacy=args.privacy, mode=args.mode, disable_comment=args.no_comment,
                               disable_duet=args.no_duet, disable_stitch=args.no_stitch, is_aigc=args.aigc)
            r = pub.publish(args.account, args.video, opts, wait=not args.no_wait, timeout=args.timeout)
            _out(args, r.to_dict(), f"{r.status} publish_id={r.publish_id}" + (f" {r.url}" if r.url else "")
                 + (f"\n{r.note}" if r.note else ""))
            return 0 if r.ok else 1
        elif args.cmd == "status":
            r = pub.status(args.account, args.publish_id)
            _out(args, r.to_dict(), f"{r.status}" + (f" {r.url}" if r.url else "") + (f" ({r.fail_reason})" if r.fail_reason else ""))
            return 0 if r.ok else 1
    except TikTokError as e:
        err = {"ok": False, "error": type(e).__name__, "code": e.code, "message": str(e)}
        if isinstance(e, PrivacyNotAllowed):
            err["allowed"] = e.allowed
        _out(args, err, f"error: {e}")
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
