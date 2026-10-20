"use client";

import { ConsoleShell } from "@/components/console-shell";
import { Alert, EmptyState, PageTitle, Skeleton } from "@/components/ui";
import { useConsoleAudit } from "@/lib/api/hooks";
import { formatWhen } from "@/lib/format";

export default function ConsoleAudit() {
  const events = useConsoleAudit();
  return (
    <ConsoleShell>
      <PageTitle
        title="Audit log"
        subtitle="Append-only. Sign-in, lookups, views, and DLQ replay."
      />
      {events.isPending && <Skeleton className="h-40 w-full rounded-3xl" />}
      {events.isError && <Alert>{events.error.message}</Alert>}
      {events.data?.length === 0 && (
        <EmptyState title="No events yet" icon={<span>A</span>}>
          Staff actions in this console are recorded here.
        </EmptyState>
      )}
      {events.data && events.data.length > 0 && (
        <ul className="flex flex-col gap-2">
          {events.data.map((event) => (
            <li key={event.id} className="rounded-2xl border border-line bg-white px-4 py-3">
              <p className="text-sm font-semibold">
                @{event.staff_handle} · {event.action}
              </p>
              <p className="text-sm text-muted">{event.detail}</p>
              <p className="mt-1 text-xs text-muted">{formatWhen(event.created_at)}</p>
            </li>
          ))}
        </ul>
      )}
    </ConsoleShell>
  );
}
