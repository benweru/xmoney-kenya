"""The rail the API talks to: the local mock or the Daraja sandbox, chosen by DARAJA_BASE_URL."""

from __future__ import annotations

from collections.abc import Iterator

from xmoney.config import get_settings
from xmoney.payments.daraja import DarajaHttpProvider
from xmoney.payments.provider import PaymentsProvider


def build_provider() -> DarajaHttpProvider:
    settings = get_settings()
    return DarajaHttpProvider(
        base_url=settings.daraja_base_url,
        consumer_key=settings.daraja_consumer_key,
        consumer_secret=settings.daraja_consumer_secret,
        shortcode=settings.daraja_shortcode,
        passkey=settings.daraja_passkey,
    )


def get_payments_provider() -> Iterator[PaymentsProvider]:
    provider = build_provider()
    try:
        yield provider
    finally:
        provider.close()
