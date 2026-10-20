"use client";

import Link from "next/link";

import { SignedInShell } from "@/components/app-shell";
import { CashOutIcon, HistoryIcon, SendIcon, TopUpIcon } from "@/components/icons";
import { TransactionList, TransactionSkeleton } from "@/components/transaction-list";
import { Alert, Button, ButtonLink, Card, EmptyState, Skeleton } from "@/components/ui";
import { useBalance, useHistory } from "@/lib/api/hooks";
import { formatKes } from "@/lib/format";

export default function HomePage() {
  return (
    <SignedInShell>
      <BalanceCard />
      <QuickActions />
      <RecentActivity />
    </SignedInShell>
  );
}

function BalanceCard() {
  const balance = useBalance();
  return (
    <section
      aria-label="Balance"
      className="relative overflow-hidden rounded-3xl bg-ink p-6 text-white shadow-lg"
    >
      <div className="pointer-events-none absolute -top-16 -right-10 size-48 rounded-full bg-brand/40 blur-2xl" />
      <p className="text-sm text-white/70">Wallet balance</p>
      {balance.isPending ? (
        <Skeleton className="mt-2 h-10 w-48 bg-white/15" />
      ) : balance.isError ? (
        <div className="mt-2 flex items-center gap-3">
          <p className="text-sm text-white/80">Couldn&apos;t load your balance.</p>
          <button
            type="button"
            onClick={() => balance.refetch()}
            className="text-sm font-semibold underline"
          >
            Retry
          </button>
        </div>
      ) : (
        <p className="mt-1 text-4xl font-bold tracking-tight tabular-nums" data-testid="balance">
          {formatKes(balance.data.balance_cents)}
        </p>
      )}
      <p className="mt-4 text-xs text-white/60">Sandbox shillings · not real money</p>
    </section>
  );
}

function QuickActions() {
  const actions = [
    { href: "/top-up/", label: "Top up", icon: TopUpIcon },
    { href: "/cash-out/", label: "Cash out", icon: CashOutIcon },
    { href: "/send/", label: "Send", icon: SendIcon },
    { href: "/history/", label: "History", icon: HistoryIcon },
  ] as const;
  return (
    <nav aria-label="Quick actions" className="grid grid-cols-2 gap-3">
      {actions.map(({ href, label, icon: ActionIcon }) => (
        <Link
          key={href}
          href={href}
          className="flex flex-col items-center gap-2 rounded-3xl border border-line bg-white py-4 text-sm font-semibold hover:border-brand/40"
        >
          <span className="flex size-11 items-center justify-center rounded-full bg-brand-soft text-brand">
            <ActionIcon className="size-5" />
          </span>
          {label}
        </Link>
      ))}
    </nav>
  );
}

function RecentActivity() {
  const history = useHistory(5);
  const items = history.data?.pages[0]?.items ?? [];
  return (
    <Card className="pb-2">
      <div className="flex items-center justify-between">
        <h2 className="text-base font-semibold">Recent activity</h2>
        {items.length > 0 && (
          <Link href="/history/" className="text-sm font-semibold text-brand">
            See all
          </Link>
        )}
      </div>
      {history.isPending ? (
        <TransactionSkeleton />
      ) : history.isError ? (
        <div className="py-3">
          <Alert
            action={
              <Button variant="secondary" onClick={() => history.refetch()}>
                Try again
              </Button>
            }
          >
            {history.error.message}
          </Alert>
        </div>
      ) : items.length === 0 ? (
        <EmptyState
          icon={<TopUpIcon className="size-6" />}
          title="No activity yet"
          action={<ButtonLink href="/top-up/">Add money from M-PESA</ButtonLink>}
        >
          Top up from M-PESA to get started. On the mock, it takes a couple of seconds.
        </EmptyState>
      ) : (
        <TransactionList items={items} />
      )}
    </Card>
  );
}
