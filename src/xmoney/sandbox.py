"""Hard stops that keep every configuration pointed at a sandbox."""

from __future__ import annotations

from urllib.parse import urlparse

from xmoney.errors import SandboxViolation

SANDBOX_DARAJA_HOST = "sandbox.safaricom.co.ke"
_SAFARICOM_DOMAIN = "safaricom.co.ke"


def assert_sandbox_daraja_host(base_url: str) -> None:
    """Refuse every Safaricom host except the public sandbox.

    Hostnames are compared after lowercasing and stripping trailing dots, so
    `API.Safaricom.co.ke.` is treated the same as `api.safaricom.co.ke`.
    """
    parsed = urlparse(base_url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise SandboxViolation("Daraja base URL must be an http(s) URL")
    host = parsed.hostname.lower().rstrip(".")
    is_safaricom = host == _SAFARICOM_DOMAIN or host.endswith("." + _SAFARICOM_DOMAIN)
    if is_safaricom and host != SANDBOX_DARAJA_HOST:
        raise SandboxViolation(
            f"refusing Safaricom host {host}; this build only talks to "
            f"{SANDBOX_DARAJA_HOST} or the local mock"
        )
