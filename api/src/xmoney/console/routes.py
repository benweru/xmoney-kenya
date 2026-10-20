"""Staff console HTTP. Read-only except DLQ replay, which does not mint."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, Response
from sqlalchemy.orm import Session

from xmoney.config import get_settings
from xmoney.console.deps import STAFF_COOKIE, current_staff
from xmoney.console.schemas import (
    ConsoleAuditEventOut,
    ConsoleDlqJobOut,
    ConsoleHistoryItemOut,
    ConsoleHistoryPageOut,
    ConsoleJournalOut,
    ConsoleJournalPostingOut,
    ConsoleReconBreakOut,
    ConsoleReconLatestOut,
    ConsoleSuspenseOut,
    ConsoleUserOut,
    StaffMeOut,
    StaffSignInIn,
)
from xmoney.console.service import (
    ConsoleUser,
    StaffActor,
    authenticate_staff,
    customer_by_id,
    customer_history,
    journal_view,
    latest_recon,
    list_audit,
    list_dlq,
    list_suspense,
    lookup_customer,
    record_audit,
    replay_dlq,
    sign_in_staff,
    sign_out_staff,
)
from xmoney.db import get_db
from xmoney.history.service import DEFAULT_LIMIT, MAX_LIMIT
from xmoney.outbox.models import OutboxJob
from xmoney.ratelimit.deps import limit_by_ip
from xmoney.ratelimit.service import CONSOLE_SIGN_IN

router = APIRouter(tags=["console"])


@router.post(
    "/console/sign-in",
    response_model=StaffMeOut,
    dependencies=[Depends(limit_by_ip(CONSOLE_SIGN_IN))],
)
def staff_sign_in(
    body: StaffSignInIn, response: Response, session: Session = Depends(get_db)
) -> StaffMeOut:
    issued = sign_in_staff(session, handle=body.handle, pin=body.pin)
    settings = get_settings()
    response.set_cookie(
        STAFF_COOKIE,
        issued.token,
        max_age=settings.session_ttl_minutes * 60,
        httponly=True,
        secure=settings.session_cookie_secure,
        samesite="lax",
        path="/",
    )
    actor = authenticate_staff(session, issued.token)
    return StaffMeOut(staff_user_id=actor.staff_user_id, handle=actor.handle)


@router.post("/console/sign-out", status_code=204)
def staff_sign_out(request: Request, session: Session = Depends(get_db)) -> Response:
    sign_out_staff(session, request.cookies.get(STAFF_COOKIE))
    response = Response(status_code=204)
    response.delete_cookie(STAFF_COOKIE, path="/")
    return response


@router.get("/console/me", response_model=StaffMeOut)
def staff_me(actor: StaffActor = Depends(current_staff)) -> StaffMeOut:
    return StaffMeOut(staff_user_id=actor.staff_user_id, handle=actor.handle)


@router.get("/console/users", response_model=ConsoleUserOut)
def console_lookup_user(
    handle: str,
    actor: StaffActor = Depends(current_staff),
    session: Session = Depends(get_db),
) -> ConsoleUserOut:
    customer = lookup_customer(session, handle)
    record_audit(
        session,
        actor,
        action="lookup_user",
        resource_type="user",
        resource_id=str(customer.user_id),
        detail=f"looked up @{customer.handle}",
    )
    return _user_out(customer)


@router.get("/console/users/{user_id}", response_model=ConsoleUserOut)
def console_get_user(
    user_id: UUID,
    actor: StaffActor = Depends(current_staff),
    session: Session = Depends(get_db),
) -> ConsoleUserOut:
    customer = customer_by_id(session, user_id)
    record_audit(
        session,
        actor,
        action="view_user",
        resource_type="user",
        resource_id=str(customer.user_id),
        detail=f"viewed @{customer.handle}",
    )
    return _user_out(customer)


@router.get("/console/users/{user_id}/ledger", response_model=ConsoleHistoryPageOut)
def console_user_ledger(
    user_id: UUID,
    limit: int = Query(default=DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
    cursor: str | None = None,
    actor: StaffActor = Depends(current_staff),
    session: Session = Depends(get_db),
) -> ConsoleHistoryPageOut:
    page = customer_history(session, user_id, limit=limit, cursor=cursor)
    record_audit(
        session,
        actor,
        action="view_ledger",
        resource_type="user",
        resource_id=str(user_id),
        detail="viewed wallet history",
    )
    return ConsoleHistoryPageOut(
        items=[
            ConsoleHistoryItemOut(
                entry_id=item.entry_id,
                kind=item.kind.value,
                amount_cents=item.amount_cents,
                counterparty=item.counterparty,
                note=item.note,
                mpesa_receipt=item.mpesa_receipt,
                created_at=item.created_at,
            )
            for item in page.items
        ],
        next_cursor=page.next_cursor,
    )


@router.get("/console/journal/{entry_id}", response_model=ConsoleJournalOut)
def console_journal(
    entry_id: UUID,
    actor: StaffActor = Depends(current_staff),
    session: Session = Depends(get_db),
) -> ConsoleJournalOut:
    view = journal_view(session, entry_id)
    record_audit(
        session,
        actor,
        action="view_journal",
        resource_type="journal_entry",
        resource_id=str(entry_id),
        detail=view.entry.description[:200],
    )
    return ConsoleJournalOut(
        id=view.entry.id,
        description=view.entry.description,
        external_ref=view.entry.external_ref,
        created_at=view.entry.created_at,
        postings=[
            ConsoleJournalPostingOut(
                line_no=posting.line_no,
                account_id=posting.account_id,
                account_code=account.code,
                direction=posting.direction,
                amount_cents=posting.amount_cents,
            )
            for posting, account in view.lines
        ],
    )


@router.get("/console/recon/latest", response_model=ConsoleReconLatestOut)
def console_recon(
    actor: StaffActor = Depends(current_staff), session: Session = Depends(get_db)
) -> ConsoleReconLatestOut:
    latest = latest_recon(session)
    record_audit(
        session,
        actor,
        action="view_recon",
        resource_type="recon_run",
        resource_id=str(latest.run.id) if latest.run else None,
        detail="viewed latest recon run",
    )
    if latest.run is None:
        return ConsoleReconLatestOut(
            run_id=None,
            started_at=None,
            finished_at=None,
            break_count=0,
            unexplained_count=0,
            breaks=[],
        )
    return ConsoleReconLatestOut(
        run_id=latest.run.id,
        started_at=latest.run.started_at,
        finished_at=latest.run.finished_at,
        break_count=latest.run.break_count,
        unexplained_count=latest.run.unexplained_count,
        breaks=[
            ConsoleReconBreakOut(
                id=row.id,
                kind=row.kind,
                subject_type=row.subject_type,
                subject_id=row.subject_id,
                our_cents=row.our_cents,
                their_cents=row.their_cents,
                detail=row.detail,
            )
            for row in latest.breaks
        ],
    )


@router.get("/console/suspense", response_model=list[ConsoleSuspenseOut])
def console_suspense(
    actor: StaffActor = Depends(current_staff), session: Session = Depends(get_db)
) -> list[ConsoleSuspenseOut]:
    items = list_suspense(session)
    record_audit(
        session,
        actor,
        action="view_suspense",
        resource_type="suspense",
        resource_id=None,
        detail=f"listed {len(items)} suspense items",
    )
    return [
        ConsoleSuspenseOut(
            id=item.id,
            status=item.status,
            amount_cents=item.amount_cents,
            open_reason=item.open_reason,
            resolve_reason=item.resolve_reason,
            recon_break_id=item.recon_break_id,
            wallet_account_id=item.wallet_account_id,
            created_at=item.created_at,
            resolved_at=item.resolved_at,
        )
        for item in items
    ]


@router.get("/console/outbox/dlq", response_model=list[ConsoleDlqJobOut])
def console_dlq(
    actor: StaffActor = Depends(current_staff), session: Session = Depends(get_db)
) -> list[ConsoleDlqJobOut]:
    jobs = list_dlq(session)
    record_audit(
        session,
        actor,
        action="view_dlq",
        resource_type="outbox",
        resource_id=None,
        detail=f"listed {len(jobs)} dead jobs",
    )
    return [_dlq_out(job) for job in jobs]


@router.post("/console/outbox/{job_id}/replay", status_code=204)
def console_replay_dlq(
    job_id: UUID,
    actor: StaffActor = Depends(current_staff),
    session: Session = Depends(get_db),
) -> Response:
    replay_dlq(session, actor, job_id)
    return Response(status_code=204)


@router.get("/console/audit", response_model=list[ConsoleAuditEventOut])
def console_audit(
    _actor: StaffActor = Depends(current_staff), session: Session = Depends(get_db)
) -> list[ConsoleAuditEventOut]:
    events = list_audit(session)
    return [
        ConsoleAuditEventOut(
            id=event.id,
            staff_handle=handle,
            action=event.action,
            resource_type=event.resource_type,
            resource_id=event.resource_id,
            detail=event.detail,
            created_at=event.created_at,
        )
        for event, handle in events
    ]


def _user_out(customer: ConsoleUser) -> ConsoleUserOut:
    return ConsoleUserOut(
        user_id=customer.user_id,
        handle=customer.handle,
        phone=customer.phone_e164,
        wallet_account_id=customer.wallet_account_id,
        balance_cents=customer.balance.balance_cents,
        created_at=customer.created_at,
    )


def _dlq_out(job: OutboxJob) -> ConsoleDlqJobOut:
    return ConsoleDlqJobOut(
        id=job.id,
        kind=job.kind,
        attempts=job.attempts,
        replays=job.replays,
        last_error=job.last_error,
        updated_at=job.updated_at,
        payload=job.payload,
    )
