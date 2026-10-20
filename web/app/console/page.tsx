"use client";

import Link from "next/link";

import { ConsoleShell } from "@/components/console-shell";
import { Alert, Card, PageTitle, Skeleton } from "@/components/ui";
import { useConsoleRecon } from "@/lib/api/hooks";

export default function ConsoleHome() {
  return (
    <ConsoleShell>
      <PageTitle
        title="Operations"
        subtitle="Lookups, recon, and the DLQ. Local staff can apply, refund, and reverse; a public https demo cannot."
      />
      <ReconCard />
      <ul className="grid gap-3 sm:grid-cols-2">
        {LINKS.map((item) => (
          <li key={item.href}>
            <Link
              href={item.href}
              className="block rounded-3xl border border-line bg-white p-5 hover:border-brand"
            >
              <p className="font-semibold">{item.title}</p>
              <p className="mt-1 text-sm text-muted">{item.body}</p>
            </Link>
          </li>
        ))}
      </ul>
    </ConsoleShell>
  );
}

const LINKS = [
  { href: "/console/users/", title: "User lookup", body: "Handle, phone, balance, history." },
  {
    href: "/console/recon/",
    title: "Recon breaks",
    body: "Latest classified run. Does not repair.",
  },
  {
    href: "/console/suspense/",
    title: "Suspense queue",
    body: "Parked value. Apply or refund locally.",
  },
  {
    href: "/console/reversals/",
    title: "Reversals",
    body: "Maker-checker for large journal reverses.",
  },
  {
    href: "/console/dlq/",
    title: "Outbox DLQ",
    body: "Replay a dead job. Does not credit wallets.",
  },
  { href: "/console/audit/", title: "Audit log", body: "Every staff action in this console." },
] as const;

function ReconCard() {
  const recon = useConsoleRecon();
  return (
    <Card>
      <p className="text-sm text-muted">Latest recon</p>
      {recon.isPending ? (
        <Skeleton className="mt-2 h-8 w-40" />
      ) : recon.isError ? (
        <Alert title="Could not load recon">{recon.error.message}</Alert>
      ) : recon.data.run_id == null ? (
        <p className="mt-1 text-base font-semibold">No run yet. `make recon` classifies breaks.</p>
      ) : (
        <p className="mt-1 text-base font-semibold">
          {recon.data.break_count} breaks · {recon.data.unexplained_count} unexplained
        </p>
      )}
    </Card>
  );
}
