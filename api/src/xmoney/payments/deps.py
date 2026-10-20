"""The rails top-ups can run on: the Daraja mock this API serves, and the Daraja sandbox.

PAYMENT_RAILS chooses which are offered, default first. Each top-up records its
rail, so STK Query and the scheduled resolver ask the rail that took the push.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator, Mapping

from xmoney.config import RailName, get_settings
from xmoney.errors import RailUnavailable
from xmoney.payments.daraja import DarajaHttpProvider
from xmoney.payments.provider import PaymentsProvider

# Top-ups created before rails were named; they ran on whichever single rail was configured.
_LEGACY_PROVIDER = "daraja"

RAIL_LABELS: dict[str, str] = {
    "mock": "Daraja mock",
    "sandbox": "Safaricom Daraja sandbox",
}


class Rails:
    """The rails this process may use. Each is built on first use and closed together."""

    def __init__(
        self,
        factories: Mapping[str, Callable[[], PaymentsProvider]],
        *,
        sandbox_phones: frozenset[str] = frozenset(),
    ) -> None:
        if not factories:
            raise ValueError("at least one rail is required")
        self._factories = dict(factories)
        self._built: dict[str, PaymentsProvider] = {}
        self.sandbox_phones = sandbox_phones

    @classmethod
    def of(cls, *providers: PaymentsProvider) -> Rails:
        """Rails that are already built, for tests and scripts. The first is the default."""
        return cls({provider.name: _built(provider) for provider in providers})

    @property
    def names(self) -> list[str]:
        return list(self._factories)

    @property
    def default(self) -> str:
        return self.names[0]

    def for_new_topup(self, name: str | None, phone_e164: str) -> PaymentsProvider:
        """The rail a visitor asked for, if it is offered and allowed for that phone."""
        chosen = name or self.default
        if chosen not in self._factories:
            raise RailUnavailable(f"the {chosen} rail is not offered here")
        if chosen == "sandbox" and self.sandbox_phones and phone_e164 not in self.sandbox_phones:
            raise RailUnavailable(
                "the Daraja sandbox rail only prompts the demo owner's test phones; "
                "use the mock rail"
            )
        return self._get(chosen)

    def for_topup(self, provider_name: str) -> PaymentsProvider | None:
        """The rail that took a top-up's push, or None if this process no longer offers it."""
        if provider_name == _LEGACY_PROVIDER and provider_name not in self._factories:
            provider_name = self.default
        if provider_name not in self._factories:
            return None
        return self._get(provider_name)

    def any(self) -> PaymentsProvider:
        """Callback parsing is the same on every rail."""
        return self._get(next(iter(self._built), self.default))

    def close(self) -> None:
        for provider in self._built.values():
            close = getattr(provider, "close", None)
            if callable(close):
                close()
        self._built.clear()

    def _get(self, name: str) -> PaymentsProvider:
        if name not in self._built:
            self._built[name] = self._factories[name]()
        return self._built[name]


def _built(provider: PaymentsProvider) -> Callable[[], PaymentsProvider]:
    return lambda: provider


def _mock() -> DarajaHttpProvider:
    # The mock checks only that credentials are present, so these are fixed.
    settings = get_settings()
    return DarajaHttpProvider(
        name="mock",
        base_url=settings.daraja_mock_base_url,
        consumer_key="sandbox",
        consumer_secret="sandbox",
        shortcode="174379",
        passkey="sandbox-passkey",
        initiator_name=settings.daraja_initiator_name,
        security_credential=settings.daraja_security_credential,
        b2c_shortcode=settings.daraja_b2c_shortcode or "174379",
    )


def _sandbox() -> DarajaHttpProvider:
    settings = get_settings()
    return DarajaHttpProvider(
        name="sandbox",
        base_url=settings.daraja_base_url,
        consumer_key=settings.daraja_consumer_key,
        consumer_secret=settings.daraja_consumer_secret,
        shortcode=settings.daraja_shortcode,
        passkey=settings.daraja_passkey,
        initiator_name=settings.daraja_initiator_name,
        security_credential=settings.daraja_security_credential,
        b2c_shortcode=settings.daraja_b2c_shortcode or settings.daraja_shortcode,
    )


_FACTORIES: dict[RailName, Callable[[], PaymentsProvider]] = {"mock": _mock, "sandbox": _sandbox}


def build_rails() -> Rails:
    settings = get_settings()
    return Rails(
        {name: _FACTORIES[name] for name in settings.payment_rails},
        sandbox_phones=frozenset(settings.daraja_sandbox_allowed_phones),
    )


def get_rails() -> Iterator[Rails]:
    rails = build_rails()
    try:
        yield rails
    finally:
        rails.close()
