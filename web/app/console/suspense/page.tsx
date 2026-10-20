"use client";

import { useState } from "react";

import { ConsoleShell, useStaff } from "@/components/console-shell";
import { Alert, Button, EmptyState, Field, Input, PageTitle, Skeleton } from "@/components/ui";
import { useApplySuspense, useConsoleSuspense, useRefundSuspense } from "@/lib/api/hooks";
import { formatKes, formatWhen, normalizeHandle } from "@/lib/format";

export default function ConsoleSuspense() {
  return (
    <ConsoleShell>
      <SuspenseBody />
    </ConsoleShell>
  );
}

function SuspenseBody() {
  const staff = useStaff();
  const items = useConsoleSuspense();
  return (
    <>
      <PageTitle
        title="Suspense"
        subtitle={
          staff.money_moving
            ? "Apply credits a wallet. Refund returns value to the M-PESA float."
            : "Read-only on this deployment. Money-moving console writes are off."
        }
      />
      {items.isPending && <Skeleton className="h-40 w-full rounded-3xl" />}
      {items.isError && <Alert>{items.error.message}</Alert>}
      {items.data?.length === 0 && (
        <EmptyState title="Queue is empty" icon={<span>S</span>}>
          Unmatched value parked from the CLI will show here.
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
              <p className="mt-1 text-sm text-muted">{item.open_reason}</p>
              {item.resolve_reason && (
                <p className="mt-1 text-sm text-muted">{item.resolve_reason}</p>
              )}
              <p className="mt-2 text-xs text-muted">{formatWhen(item.created_at)}</p>
              {staff.money_moving && item.status === "open" && <SuspenseActions id={item.id} />}
            </li>
          ))}
        </ul>
      )}
    </>
  );
}

function SuspenseActions({ id }: { id: string }) {
  const apply = useApplySuspense();
  const refund = useRefundSuspense();
  const [handle, setHandle] = useState("");
  const [reason, setReason] = useState("");
  const error = apply.error ?? refund.error;
  return (
    <div className="mt-4 flex flex-col gap-3">
      {error && <Alert>{error.message}</Alert>}
      <Field label="Apply to handle" htmlFor={`handle-${id}`}>
        <Input
          id={`handle-${id}`}
          prefix="@"
          value={handle}
          onChange={(e) => setHandle(e.target.value)}
        />
      </Field>
      <Field label="Reason" htmlFor={`reason-${id}`}>
        <Input id={`reason-${id}`} value={reason} onChange={(e) => setReason(e.target.value)} />
      </Field>
      <div className="grid gap-2 sm:grid-cols-2">
        <Button
          loading={apply.isPending}
          onClick={() =>
            apply.mutate({ itemId: id, handle: normalizeHandle(handle), reason: reason.trim() })
          }
        >
          Apply
        </Button>
        <Button
          variant="secondary"
          loading={refund.isPending}
          onClick={() => refund.mutate({ itemId: id, reason: reason.trim() })}
        >
          Refund to float
        </Button>
      </div>
    </div>
  );
}
