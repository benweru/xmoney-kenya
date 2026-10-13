"use client";

import { SignedInShell } from "@/components/app-shell";
import { HistoryIcon } from "@/components/icons";
import { TransactionList, TransactionSkeleton } from "@/components/transaction-list";
import { Alert, Button, ButtonLink, Card, EmptyState, PageTitle } from "@/components/ui";
import { useHistory } from "@/lib/api/hooks";

export default function HistoryPage() {
  return (
    <SignedInShell>
      <History />
    </SignedInShell>
  );
}

function History() {
  const history = useHistory(20);
  const items = history.data?.pages.flatMap((page) => page.items) ?? [];

  return (
    <>
      <PageTitle title="History" subtitle="Every top-up and send, newest first." />
      <Card className="py-2">
        {history.isPending ? (
          <TransactionSkeleton rows={6} />
        ) : history.isError && items.length === 0 ? (
          <div className="py-3">
            <Alert
              title="Can't load your history"
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
            icon={<HistoryIcon className="size-6" />}
            title="Nothing here yet"
            action={<ButtonLink href="/top-up/">Top up</ButtonLink>}
          >
            Top-ups and sends show up here as soon as they happen.
          </EmptyState>
        ) : (
          <TransactionList items={items} />
        )}
      </Card>
      {history.hasNextPage && (
        <Button
          variant="secondary"
          loading={history.isFetchingNextPage}
          onClick={() => history.fetchNextPage()}
        >
          Load more
        </Button>
      )}
      {history.isFetchNextPageError && <Alert>{history.error?.message}</Alert>}
    </>
  );
}
