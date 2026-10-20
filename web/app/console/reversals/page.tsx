"use client";

import { useState } from "react";

import { ConsoleShell, useStaff } from "@/components/console-shell";
import { Alert, Button, EmptyState, Field, Input, PageTitle, Skeleton } from "@/components/ui";
import { useApproveReversal, useConsoleReversals, useRejectReversal } from "@/lib/api/hooks";
import { formatKes, formatWhen } from "@/lib/format";

export default function ConsoleReversals() {
  return (
    <ConsoleShell>
      <ReversalsBody />
    </ConsoleShell>
  );
}

function ReversalsBody() {
  const staff = useStaff();
  const items = useConsoleReversals();
  return (
    <>
      <PageTitle
        title="Reversals"
        subtitle={
          staff.money_moving
            ? "Proposed full reversals. The maker cannot approve their own row."
            : "Read-only on this deployment. Money-moving console writes are off."
        }
      />
      {items.isPending && <Skeleton className="h-40 w-full rounded-3xl" />}
      {items.isError && <Alert>{items.error.message}</Alert>}
      {items.data?.length === 0 && (
        <EmptyState title="Nothing waiting" icon={<span>R</span>}>
          Propose a reversal from a user&apos;s journal. Large ones stay here until a second staff
          user approves.
        </EmptyState>
      )}
      {items.data && items.data.length > 0 && (
        <ul className="flex flex-col gap-3">
          {items.data.map((item) => (
            <li key={item.id} className="rounded-3xl border border-line bg-white p-5">
              <div className="flex items-center justify-between gap-3">
                <p className="font-semibold">{item.status}</p>
                <p className="font-semibold">{formatKes(item.amount_cents)}</p>
              </div>
              <p className="mt-1 text-sm text-muted">{item.reason}</p>
              <p className="mt-1 text-xs text-muted">
                maker @{item.maker}
                {item.checker ? ` · checker @${item.checker}` : ""} · {formatWhen(item.created_at)}
              </p>
              {staff.money_moving && item.status === "proposed" && (
                <ReversalActions id={item.id} maker={item.maker} me={staff.handle} />
              )}
            </li>
          ))}
        </ul>
      )}
    </>
  );
}

function ReversalActions({ id, maker, me }: { id: string; maker: string; me: string }) {
  const approve = useApproveReversal();
  const reject = useRejectReversal();
  const [reason, setReason] = useState("");
  const error = approve.error ?? reject.error;
  const self = maker === me;
  return (
    <div className="mt-4 flex flex-col gap-3">
      {self && (
        <p className="text-sm text-muted">
          Sign in as a different staff user to approve or reject.
        </p>
      )}
      {error && <Alert>{error.message}</Alert>}
      <Field label="Reject reason" htmlFor={`reject-${id}`}>
        <Input id={`reject-${id}`} value={reason} onChange={(e) => setReason(e.target.value)} />
      </Field>
      <div className="grid gap-2 sm:grid-cols-2">
        <Button loading={approve.isPending} disabled={self} onClick={() => approve.mutate(id)}>
          Approve
        </Button>
        <Button
          variant="secondary"
          loading={reject.isPending}
          disabled={self}
          onClick={() => reject.mutate({ reversalId: id, reason: reason.trim() })}
        >
          Reject
        </Button>
      </div>
    </div>
  );
}
