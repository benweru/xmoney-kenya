"use client";

import { useState, type FormEvent } from "react";

import { ConsoleShell, useStaff } from "@/components/console-shell";
import { Alert, Button, Card, Field, Input, PageTitle, Skeleton } from "@/components/ui";
import {
  useConsoleJournal,
  useConsoleReversals,
  useConsoleUser,
  useConsoleUserLedger,
  useProposeReversal,
} from "@/lib/api/hooks";
import { formatKes, formatWhen, normalizeHandle } from "@/lib/format";

export default function ConsoleUsers() {
  const [typed, setTyped] = useState("amina");
  const [handle, setHandle] = useState<string | null>(null);
  const [entryId, setEntryId] = useState<string | null>(null);

  function submit(event: FormEvent) {
    event.preventDefault();
    setEntryId(null);
    setHandle(normalizeHandle(typed) || null);
  }

  return (
    <ConsoleShell>
      <PageTitle
        title="User lookup"
        subtitle="Staff can see the phone number. This screen does not move money."
      />
      <form onSubmit={submit} className="flex flex-col gap-3 sm:flex-row sm:items-end">
        <Field label="Handle" htmlFor="handle">
          <Input id="handle" prefix="@" value={typed} onChange={(e) => setTyped(e.target.value)} />
        </Field>
        <Button type="submit" className="sm:w-40">
          Look up
        </Button>
      </form>
      {handle && <UserPanel handle={handle} entryId={entryId} onOpenEntry={setEntryId} />}
    </ConsoleShell>
  );
}

function UserPanel({
  handle,
  entryId,
  onOpenEntry,
}: {
  handle: string;
  entryId: string | null;
  onOpenEntry: (id: string) => void;
}) {
  const user = useConsoleUser(handle);
  const ledger = useConsoleUserLedger(user.data?.user_id ?? null);

  if (user.isPending) return <Skeleton className="h-40 w-full rounded-3xl" />;
  if (user.isError) return <Alert>{user.error.message}</Alert>;

  return (
    <>
      <Card>
        <p className="text-sm text-muted">@{user.data.handle}</p>
        <p className="text-2xl font-bold">{formatKes(user.data.balance_cents)}</p>
        <p className="mt-2 text-sm text-muted">{user.data.phone}</p>
      </Card>
      <Card className="p-0">
        <ul className="divide-y divide-line">
          {ledger.isPending && (
            <li className="p-5">
              <Skeleton className="h-6 w-full" />
            </li>
          )}
          {ledger.isError && (
            <li className="p-5">
              <Alert>{ledger.error.message}</Alert>
            </li>
          )}
          {ledger.data?.items.length === 0 && (
            <li className="p-5 text-sm text-muted">No journal entries on this wallet.</li>
          )}
          {ledger.data?.items.map((item) => (
            <li key={item.entry_id}>
              <button
                type="button"
                onClick={() => onOpenEntry(item.entry_id)}
                className="flex w-full items-center justify-between gap-3 px-5 py-4 text-left hover:bg-surface"
              >
                <span>
                  <span className="font-medium">{item.kind}</span>
                  {item.counterparty && (
                    <span className="ml-2 text-sm text-muted">@{item.counterparty}</span>
                  )}
                  <span className="mt-0.5 block text-xs text-muted">
                    {formatWhen(item.created_at)}
                  </span>
                </span>
                <span className="font-semibold">{formatKes(item.amount_cents)}</span>
              </button>
            </li>
          ))}
        </ul>
      </Card>
      {entryId && <JournalCard entryId={entryId} />}
    </>
  );
}

function JournalCard({ entryId }: { entryId: string }) {
  const staff = useStaff();
  const journal = useConsoleJournal(entryId);
  const reversals = useConsoleReversals(entryId);
  const propose = useProposeReversal();
  const [reason, setReason] = useState("");
  if (journal.isPending) return <Skeleton className="h-32 w-full rounded-3xl" />;
  if (journal.isError) return <Alert>{journal.error.message}</Alert>;
  const active = reversals.data?.find(
    (row) => row.status === "proposed" || row.status === "posted",
  );
  return (
    <Card>
      <p className="font-semibold">{journal.data.description}</p>
      <ul className="mt-3 space-y-2 text-sm">
        {journal.data.postings.map((line) => (
          <li key={line.line_no} className="flex justify-between gap-3">
            <span>
              {line.direction} {line.account_code}
            </span>
            <span className="font-medium">{formatKes(line.amount_cents)}</span>
          </li>
        ))}
      </ul>
      {active && (
        <p className="mt-3 text-sm text-muted">
          Reversal {active.status} ({formatKes(active.amount_cents)}) by @{active.maker}.
        </p>
      )}
      {staff.money_moving && !active && (
        <div className="mt-4 flex flex-col gap-3">
          {propose.error && <Alert>{propose.error.message}</Alert>}
          <Field label="Reverse reason" htmlFor="reverse-reason">
            <Input id="reverse-reason" value={reason} onChange={(e) => setReason(e.target.value)} />
          </Field>
          <Button
            variant="secondary"
            loading={propose.isPending}
            onClick={() =>
              propose.mutate({ original_journal_entry_id: entryId, reason: reason.trim() })
            }
          >
            Propose reversal
          </Button>
        </div>
      )}
    </Card>
  );
}
