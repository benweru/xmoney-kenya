"use client";

import { ConsoleShell } from "@/components/console-shell";
import { Alert, EmptyState, PageTitle, Skeleton } from "@/components/ui";
import { useConsoleSuspense } from "@/lib/api/hooks";
import { formatKes, formatWhen } from "@/lib/format";

export default function ConsoleSuspense() {
  const items = useConsoleSuspense();
  return (
    <ConsoleShell>
      <PageTitle
        title="Suspense"
        subtitle="Read-only. Apply or refund with `make suspense`. That is still not HTTP."
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
              <p className="mt-2 text-xs text-muted">{formatWhen(item.created_at)}</p>
            </li>
          ))}
        </ul>
      )}
    </ConsoleShell>
  );
}
