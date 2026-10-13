"""Top up a wallet end to end against a running API, on the mock or the Daraja sandbox.

    python scripts/topup_smoke.py --phone +254708374149 --amount 1

Registers the handle if it is new, signs in with the code from the sandbox
inbox, starts an STK Push, and polls until the top-up is final. With the real
sandbox, approve the prompt on the handset. Exits 0 only if it succeeded.
"""

from __future__ import annotations

import argparse
import re
import sys
import time
import uuid

import httpx

_CODE_RE = re.compile(r"code is (\d{6})")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--api", default="http://127.0.0.1:8000")
    parser.add_argument("--handle", default="smoketest")
    parser.add_argument("--phone", required=True, help="E.164, for example +254708374149")
    parser.add_argument("--pin", default="2580")
    parser.add_argument("--amount", type=int, default=1, help="whole shillings")
    parser.add_argument("--wait", type=int, default=360, help="seconds to wait for a result")
    args = parser.parse_args()

    with httpx.Client(base_url=args.api, timeout=30.0) as http:
        registered = http.post(
            "/v1/users", json={"handle": args.handle, "phone": args.phone, "pin": args.pin}
        )
        if registered.status_code not in (201, 409):
            return _fail("register", registered)

        challenge = http.post("/v1/auth/sign-in", json={"phone": args.phone, "pin": args.pin})
        if challenge.status_code != 200:
            return _fail("sign-in", challenge)
        inbox = http.get("/v1/sandbox/inbox", params={"phone": args.phone}).json()
        match = _CODE_RE.search(inbox[0]["body"]) if inbox else None
        if match is None:
            print("no sign-in code in the sandbox inbox", file=sys.stderr)
            return 1
        verified = http.post(
            "/v1/auth/verify",
            json={"challenge_id": challenge.json()["challenge_id"], "code": match.group(1)},
        )
        if verified.status_code != 200:
            return _fail("verify", verified)
        wallet = verified.json()["wallet_account_id"]
        print(f"signed in as @{verified.json()['handle']}")

        started = http.post(
            "/v1/topups",
            json={"amount_cents": args.amount * 100},
            headers={"Idempotency-Key": f"smoke-{uuid.uuid4()}"},
        )
        if started.status_code not in (200, 201):
            return _fail("top-up", started)
        topup = started.json()
        print(f"STK Push sent: {topup['checkout_request_id']} ({topup['status']})")

        deadline = time.monotonic() + args.wait
        while topup["status"] in ("initiated", "pending") and time.monotonic() < deadline:
            time.sleep(3)
            topup = http.get(f"/v1/topups/{topup['id']}").json()
            print(f"  {topup['status']}")

        balance = http.get(f"/v1/accounts/{wallet}/balance").json()["balance_cents"]
        print(
            f"final: {topup['status']} result_code={topup['result_code']} "
            f"receipt={topup['mpesa_receipt_number']} wallet=KES {balance / 100:.2f}"
        )
        return 0 if topup["status"] == "succeeded" else 1


def _fail(step: str, response: httpx.Response) -> int:
    print(f"{step} failed: HTTP {response.status_code} {response.text}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
