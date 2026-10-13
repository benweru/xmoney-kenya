"use client";

import { SignedInShell, useSignedInUser } from "@/components/app-shell";
import { InboxIcon } from "@/components/icons";
import { TransactionSkeleton } from "@/components/transaction-list";
import { Alert, Card, EmptyState, PageTitle } from "@/components/ui";
import { useInbox } from "@/lib/api/hooks";
import { formatPhone, formatWhen } from "@/lib/format";

export default function InboxPage() {
  return (
    <SignedInShell>
      <Inbox />
    </SignedInShell>
  );
}

function Inbox() {
  const me = useSignedInUser();
  const inbox = useInbox(me.phone);
  return (
    <>
      <PageTitle
        title="Sandbox inbox"
        subtitle={
          <>Messages that would be texted to {formatPhone(me.phone)}. The demo never sends SMS.</>
        }
      />
      <Alert tone="warn">
        Anyone who knows a phone number can read its sandbox inbox. That is fine only because this
        is a sandbox.
      </Alert>
      <Card className="py-2">
        {inbox.isPending ? (
          <TransactionSkeleton />
        ) : inbox.isError ? (
          <div className="py-3">
            <Alert>{inbox.error.message}</Alert>
          </div>
        ) : inbox.data.length === 0 ? (
          <EmptyState icon={<InboxIcon className="size-6" />} title="No messages" />
        ) : (
          <ul className="divide-y divide-line">
            {inbox.data.map((message) => (
              <li
                key={`${message.created_at}-${message.body}`}
                className="flex flex-col gap-1 py-3"
              >
                <span className="text-sm">{message.body}</span>
                <span className="text-xs text-muted">{formatWhen(message.created_at)}</span>
              </li>
            ))}
          </ul>
        )}
      </Card>
    </>
  );
}
