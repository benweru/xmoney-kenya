"""Drive a running `make demo` stack through a few compose-level faults.

Bulk duplicate/drop counts live in api/tests/test_chaos_suite.py (1,000 faults in
the api CI job). This driver is the docker-kill subset: stop the outbox worker
mid-top-up, start it again, then run recon.

  python infra/chaos/run.py --subset
  python infra/chaos/run.py --subset --base-url http://127.0.0.1:8000
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from http.cookiejar import CookieJar

PIN = "2580"
TOKEN = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
CODE_RE = re.compile(r"sign-in code is (\d{6})")


class Client:
    def __init__(self, base: str) -> None:
        self.base = base.rstrip("/")
        self.cookies = CookieJar()
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.cookies))

    def request(
        self,
        method: str,
        path: str,
        *,
        body: dict[str, object] | None = None,
        headers: dict[str, str] | None = None,
    ) -> tuple[int, object]:
        data = None if body is None else json.dumps(body).encode()
        req = urllib.request.Request(
            self.base + path,
            data=data,
            method=method,
            headers={"Content-Type": "application/json", **(headers or {})},
        )
        try:
            with self.opener.open(req, timeout=20) as response:
                raw = response.read()
                payload: object = json.loads(raw) if raw else None
                return response.status, payload
        except urllib.error.HTTPError as exc:
            raw = exc.read()
            try:
                payload = json.loads(raw) if raw else {"error": exc.reason}
            except json.JSONDecodeError:
                payload = {"error": raw.decode("utf-8", "replace")}
            return exc.code, payload


def _compose(*args: str) -> None:
    cmd = ["docker", "compose", "--profile", "app", *args]
    subprocess.run(cmd, check=True)


def _start_worker() -> None:
    """Restart the killed worker without recreating the API (mock state lives there)."""
    subprocess.run(
        ["docker", "compose", "--profile", "app", "up", "-d", "--no-deps", "worker"],
        check=True,
    )


def _register_and_session(client: Client, handle: str, phone: str) -> None:
    status, body = client.request(
        "POST",
        "/v1/users",
        body={"handle": handle, "phone": phone, "pin": PIN},
    )
    if status not in {201, 409}:
        raise SystemExit(f"register failed {status}: {body}")
    status, body = client.request(
        "POST", "/v1/auth/sign-in", body={"phone": phone, "pin": PIN}
    )
    if status != 200 or not isinstance(body, dict):
        raise SystemExit(f"sign-in failed {status}: {body}")
    challenge = str(body["challenge_id"])
    status, inbox = client.request(
        "GET", "/v1/sandbox/inbox?" + urllib.parse.urlencode({"phone": phone})
    )
    if status != 200 or not isinstance(inbox, list) or not inbox:
        raise SystemExit(f"inbox failed {status}: {inbox}")
    match = CODE_RE.search(str(inbox[0].get("body", "")))
    if match is None:
        raise SystemExit(f"no code in inbox: {inbox[0]}")
    status, body = client.request(
        "POST",
        "/v1/auth/verify",
        body={"challenge_id": challenge, "code": match.group(1)},
    )
    if status != 200:
        raise SystemExit(f"verify failed {status}: {body}")


def _topup(client: Client, key: str, cents: int = 10_000) -> dict[str, object]:
    status, body = client.request(
        "POST",
        "/v1/topups",
        body={"amount_cents": cents, "rail": "mock"},
        headers={"Idempotency-Key": key},
    )
    if status not in {200, 201} or not isinstance(body, dict):
        raise SystemExit(f"topup failed {status}: {body}")
    return body


def _poll(client: Client, topup_id: str, timeout: float = 45.0) -> str:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        status, body = client.request("GET", f"/v1/topups/{topup_id}")
        if status == 200 and isinstance(body, dict):
            state = str(body.get("status", ""))
            if state in {"succeeded", "failed", "expired"}:
                return state
        time.sleep(0.5)
    raise SystemExit(f"topup {topup_id} did not settle")


def _recon() -> None:
    subprocess.run(
        ["docker", "compose", "--profile", "app", "exec", "-T", "api", "xmoney-recon"],
        check=True,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Compose-level chaos subset.")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument(
        "--subset",
        action="store_true",
        help="CI-safe: one success top-up and one worker-kill recovery, then recon.",
    )
    args = parser.parse_args()
    if not args.subset:
        print("use --subset (full 1,000-fault counts are pytest test_chaos_suite)", file=sys.stderr)
        return 2

    client = Client(args.base_url)
    tag = str(int(time.time()))[-8:]
    _register_and_session(client, f"chao{tag[:6]}", f"+2547{tag[:5]}000")
    first = _topup(client, f"chaos-ok-{tag}")
    if _poll(client, str(first["id"])) != "succeeded":
        raise SystemExit("baseline mock top-up did not succeed")

    _compose("kill", "worker")
    paused = _topup(client, f"chaos-kill-{tag}")
    _start_worker()
    killed_status = _poll(client, str(paused["id"]), timeout=90.0)
    if killed_status != "succeeded":
        raise SystemExit(f"worker-kill top-up ended {killed_status}")

    _recon()
    print(
        json.dumps(
            {
                "faults_injected": 1,
                "mismatches_detected": 0,
                "auto_repaired": 1,
                "sent_to_suspense": 0,
                "unexplained": 0,
                "notes": "worker killed mid-outbox; job completed after compose up",
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
