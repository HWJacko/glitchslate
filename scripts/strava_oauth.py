from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any


AUTH_URL = "https://www.strava.com/oauth/authorize"
TOKEN_URL = "https://www.strava.com/oauth/token"


def load_env(path: Path = Path(".env")) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        os.environ.setdefault(key, value.strip().strip("'\""))


def required_env() -> tuple[str, str]:
    client_id = os.getenv("STRAVA_CLIENT_ID")
    client_secret = os.getenv("STRAVA_CLIENT_SECRET")
    missing = [key for key, value in {"STRAVA_CLIENT_ID": client_id, "STRAVA_CLIENT_SECRET": client_secret}.items() if not value]
    if missing:
        raise RuntimeError(f"missing {', '.join(missing)}")
    return str(client_id), str(client_secret)


def build_authorize_url(*, client_id: str, redirect_uri: str, scope: str) -> str:
    query = urllib.parse.urlencode(
        {
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "approval_prompt": "force",
            "scope": scope,
        }
    )
    return f"{AUTH_URL}?{query}"


def exchange_code(*, client_id: str, client_secret: str, code: str) -> dict[str, Any]:
    data = urllib.parse.urlencode(
        {
            "client_id": client_id,
            "client_secret": client_secret,
            "code": code,
            "grant_type": "authorization_code",
        }
    ).encode("utf-8")
    request = urllib.request.Request(TOKEN_URL, data=data)
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", "replace")
        raise RuntimeError(f"Strava token exchange failed with HTTP {exc.code}: {body}") from exc


def update_env_value(path: Path, key: str, value: str) -> None:
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    prefix = f"{key}="
    for index, line in enumerate(lines):
        if line.startswith(prefix):
            lines[index] = f"{key}={value}"
            break
    else:
        lines.append(f"{key}={value}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def command_authorize(args: argparse.Namespace) -> int:
    load_env(args.env)
    client_id, _ = required_env()
    print(build_authorize_url(client_id=client_id, redirect_uri=args.redirect_uri, scope=args.scope))
    return 0


def command_exchange(args: argparse.Namespace) -> int:
    load_env(args.env)
    client_id, client_secret = required_env()
    payload = exchange_code(client_id=client_id, client_secret=client_secret, code=args.code)
    scope = str(payload.get("scope", ""))
    print(f"scope={scope or '<not returned>'}")
    print(f"athlete_id={(payload.get('athlete') or {}).get('id', '<not returned>')}")
    print(f"expires_at={payload.get('expires_at', '<not returned>')}")
    print(f"refresh_token_length={len(str(payload.get('refresh_token', '')))}")

    if args.update_env:
        refresh_token = payload.get("refresh_token")
        if not refresh_token:
            raise RuntimeError("token exchange did not return a refresh_token")
        update_env_value(args.env, "STRAVA_REFRESH_TOKEN", str(refresh_token))
        print(f"updated {args.env}: STRAVA_REFRESH_TOKEN")

    if "activity:read" not in scope and "activity:read_all" not in scope:
        print("warning: granted scope does not include activity:read or activity:read_all", file=sys.stderr)
        return 1
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Authorize Glitchslate with Strava OAuth.")
    parser.add_argument("--env", type=Path, default=Path(".env"))
    subparsers = parser.add_subparsers(dest="command", required=True)

    authorize = subparsers.add_parser("authorize-url", help="Print the Strava authorization URL.")
    authorize.add_argument("--redirect-uri", default="http://localhost")
    authorize.add_argument("--scope", default="activity:read")
    authorize.set_defaults(func=command_authorize)

    exchange = subparsers.add_parser("exchange-code", help="Exchange a redirected OAuth code for tokens.")
    exchange.add_argument("code")
    exchange.add_argument("--update-env", action="store_true")
    exchange.set_defaults(func=command_exchange)

    args = parser.parse_args()
    try:
        return int(args.func(args))
    except RuntimeError as exc:
        print(exc, file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
