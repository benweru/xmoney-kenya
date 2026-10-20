"""Database engine and session dependency."""

from __future__ import annotations

from collections.abc import Iterator

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from xmoney.config import get_settings


class Base(DeclarativeBase):
    pass


def import_mapped_tables() -> None:
    """Register every mapped table on Base. Isolated processes (the worker) need this.

    A process that only imports `Topup` cannot resolve `topups.user_id` until `User`
    is imported. The API loads models through routes; the worker does not.
    """
    from xmoney.auth import models as auth_models  # noqa: F401
    from xmoney.identity import models as identity_models  # noqa: F401
    from xmoney.inbox import models as inbox_models  # noqa: F401
    from xmoney.ledger import models as ledger_models  # noqa: F401
    from xmoney.outbox import models as outbox_models  # noqa: F401
    from xmoney.payments import models as payments_models  # noqa: F401
    from xmoney.ratelimit import models as ratelimit_models  # noqa: F401
    from xmoney.recon import models as recon_models  # noqa: F401
    from xmoney.reversals import models as reversals_models  # noqa: F401
    from xmoney.suspense import models as suspense_models  # noqa: F401
    from xmoney.transfers import models as transfers_models  # noqa: F401


_engine: Engine | None = None
_sessionmaker: sessionmaker[Session] | None = None


def get_engine() -> Engine:
    global _engine, _sessionmaker
    if _engine is None:
        _engine = create_engine(get_settings().sqlalchemy_url, pool_pre_ping=True)
        _sessionmaker = sessionmaker(bind=_engine, autoflush=False, expire_on_commit=False)
    return _engine


def get_sessionmaker() -> sessionmaker[Session]:
    get_engine()
    assert _sessionmaker is not None
    return _sessionmaker


def release_read_transaction(session: Session) -> None:
    """End an autobegun read-only transaction so the caller can open its own.

    Raises instead of silently discarding pending ORM changes. Work the caller
    already flushed is not detectable here, so services that own their
    transaction must be called before any writes, not after.
    """
    if not session.in_transaction():
        return
    if session.new or session.dirty or session.deleted:
        raise RuntimeError(
            "session has pending changes; commit or roll back before calling a "
            "service that owns its own transaction"
        )
    session.rollback()


def get_db() -> Iterator[Session]:
    session = get_sessionmaker()()
    try:
        yield session
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
