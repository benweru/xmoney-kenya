import type { HistoryItem } from "@/lib/api/client";
import { formatSignedKes, formatWhen } from "@/lib/format";

import { ArrowDownLeftIcon, ArrowUpRightIcon, CashOutIcon, TopUpIcon, WalletIcon } from "./icons";
import { Skeleton, cx } from "./ui";

function describe(item: HistoryItem): { title: string; icon: typeof TopUpIcon } {
  switch (item.kind) {
    case "topup":
      return { title: "M-PESA top-up", icon: TopUpIcon };
    case "cashout":
      return { title: "M-PESA cash-out", icon: CashOutIcon };
    case "cashout_return":
      return { title: "Cash-out returned", icon: TopUpIcon };
    case "transfer_in":
      return { title: `From @${item.counterparty ?? "someone"}`, icon: ArrowDownLeftIcon };
    case "transfer_out":
      return { title: `To @${item.counterparty ?? "someone"}`, icon: ArrowUpRightIcon };
    default:
      return { title: "Adjustment", icon: WalletIcon };
  }
}

export function TransactionRow({ item }: { item: HistoryItem }) {
  const { title, icon: RowIcon } = describe(item);
  const incoming = item.amount_cents > 0;
  const detail = item.note ?? (item.mpesa_receipt ? `Receipt ${item.mpesa_receipt}` : null);
  return (
    <li className="flex items-center gap-3 py-3" data-testid="transaction">
      <span
        className={cx(
          "flex size-10 shrink-0 items-center justify-center rounded-full",
          incoming ? "bg-brand-soft text-brand" : "bg-surface text-ink",
        )}
      >
        <RowIcon className="size-5" />
      </span>
      <span className="flex min-w-0 flex-1 flex-col">
        <span className="truncate font-medium">{title}</span>
        {detail && <span className="truncate text-xs text-muted">{detail}</span>}
      </span>
      <span className="flex shrink-0 flex-col items-end">
        <span
          className={cx("text-sm font-semibold tabular-nums", incoming ? "text-brand" : "text-ink")}
        >
          {formatSignedKes(item.amount_cents)}
        </span>
        <span className="text-xs text-muted">{formatWhen(item.created_at)}</span>
      </span>
    </li>
  );
}

export function TransactionList({ items }: { items: HistoryItem[] }) {
  return (
    <ul className="divide-y divide-line" aria-label="Transactions">
      {items.map((item) => (
        <TransactionRow key={item.id} item={item} />
      ))}
    </ul>
  );
}

export function TransactionSkeleton({ rows = 3 }: { rows?: number }) {
  return (
    <ul className="divide-y divide-line" aria-busy="true" aria-label="Loading transactions">
      {Array.from({ length: rows }, (_, i) => (
        <li key={i} className="flex items-center gap-3 py-3">
          <Skeleton className="size-10 rounded-full" />
          <span className="flex flex-1 flex-col gap-1.5">
            <Skeleton className="h-4 w-32" />
            <Skeleton className="h-3 w-20" />
          </span>
          <Skeleton className="h-4 w-16" />
        </li>
      ))}
    </ul>
  );
}
