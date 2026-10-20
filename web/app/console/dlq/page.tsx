"use client";

import { ConsoleShell } from "@/components/console-shell";
import { Alert, Button, EmptyState, PageTitle, Skeleton } from "@/components/ui";
import { useConsoleDlq, useReplayDlq } from "@/lib/api/hooks";
import { formatWhen } from "@/lib/format";

export default function ConsoleDlq() {
  const jobs = useConsoleDlq();
  const replay = useReplayDlq();
  return (
    <ConsoleShell>
      <PageTitle
        title="Dead-letter queue"
        subtitle="Replay puts a dead outbox job back. It does not credit a wallet."
      />
      {jobs.isPending && <Skeleton className="h-40 w-full rounded-3xl" />}
      {jobs.isError && <Alert>{jobs.error.message}</Alert>}
      {replay.error && <Alert>{replay.error.message}</Alert>}
      {jobs.data?.length === 0 && (
        <EmptyState title="No dead jobs" icon={<span>Q</span>}>
          Failed rail work lands here after it runs out of attempts.
        </EmptyState>
      )}
      {jobs.data && jobs.data.length > 0 && (
        <ul className="flex flex-col gap-3">
          {jobs.data.map((job) => (
            <li key={job.id} className="rounded-3xl border border-line bg-white p-5">
              <p className="font-semibold">{job.kind}</p>
              <p className="mt-1 text-sm text-muted">{job.last_error ?? "no error text"}</p>
              <p className="mt-1 text-xs text-muted">
                {job.attempts} attempts · {job.replays} replays · {formatWhen(job.updated_at)}
              </p>
              <Button
                className="mt-3"
                variant="secondary"
                loading={replay.isPending && replay.variables === job.id}
                onClick={() => replay.mutate(job.id)}
              >
                Replay
              </Button>
            </li>
          ))}
        </ul>
      )}
    </ConsoleShell>
  );
}
