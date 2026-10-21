"use client";

import { ConsoleShell } from "@/components/console-shell";
import { Alert, Card, EmptyState, PageTitle, Skeleton } from "@/components/ui";
import { useConsoleRecon } from "@/lib/api/hooks";
import { formatKes } from "@/lib/format";

export default function ConsoleRecon() {
  const recon = useConsoleRecon();
  return (
    <ConsoleShell>
      <PageTitle
        title="Reconciliation"
        subtitle="Classified breaks, including rail-paid with no callback. Closing suspense quiets the next run."
      />
      {recon.isPending && <Skeleton className="h-40 w-full rounded-3xl" />}
      {recon.isError && <Alert>{recon.error.message}</Alert>}
      {recon.data && recon.data.run_id == null && (
        <EmptyState title="No recon run yet" icon={<span>R</span>}>
          Run `make recon` against the API database.
        </EmptyState>
      )}
      {recon.data?.run_id && (
        <>
          <Card>
            <p className="text-sm text-muted">Run {recon.data.run_id}</p>
            <p className="text-lg font-semibold">
              {recon.data.break_count} breaks · {recon.data.unexplained_count} unexplained
            </p>
          </Card>
          <ul className="flex flex-col gap-3">
            {recon.data.breaks.map((row) => (
              <li key={row.id} className="rounded-3xl border border-line bg-white p-5">
                <p className="font-semibold">
                  {row.kind}
                  {row.quieted_at ? " · quieted" : ""}
                </p>
                <p className="mt-1 text-sm text-muted">{row.detail}</p>
                {(row.our_cents != null || row.their_cents != null) && (
                  <p className="mt-2 text-sm">
                    ours {row.our_cents != null ? formatKes(row.our_cents) : "—"} · theirs{" "}
                    {row.their_cents != null ? formatKes(row.their_cents) : "—"}
                  </p>
                )}
              </li>
            ))}
          </ul>
        </>
      )}
    </ConsoleShell>
  );
}
