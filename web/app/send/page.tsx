"use client";

import { useState, type FormEvent } from "react";

import { SignedInShell, useSignedInUser } from "@/components/app-shell";
import { CheckIcon } from "@/components/icons";
import { Alert, Button, ButtonLink, Card, Field, Input, PageTitle } from "@/components/ui";
import type { Transfer } from "@/lib/api/client";
import { newIdempotencyKey, useBalance, useLookupHandle, useSend } from "@/lib/api/hooks";
import { formatKes, normalizeHandle, parseKesToCents } from "@/lib/format";

type Draft = { to: string; cents: number; note: string; key: string };

export default function SendPage() {
  return (
    <SignedInShell>
      <Send />
    </SignedInShell>
  );
}

function Send() {
  const [draft, setDraft] = useState<Draft | null>(null);
  const [sent, setSent] = useState<Transfer | null>(null);

  if (sent)
    return (
      <Sent
        transfer={sent}
        onAgain={() => {
          setSent(null);
          setDraft(null);
        }}
      />
    );
  if (draft) return <Confirm draft={draft} onBack={() => setDraft(null)} onSent={setSent} />;
  return <Compose onReady={setDraft} />;
}

function Compose({ onReady }: { onReady: (draft: Draft) => void }) {
  const me = useSignedInUser();
  const balance = useBalance();
  const lookup = useLookupHandle();
  const [to, setTo] = useState("");
  const [amount, setAmount] = useState("");
  const [note, setNote] = useState("");
  const [touched, setTouched] = useState(false);

  const handle = normalizeHandle(to);
  const cents = parseKesToCents(amount);
  const self = handle === me.handle;
  const toError =
    touched && (!handle ? "Who are you paying?" : self ? "You can't send to yourself." : null);
  const amountError = touched && cents === null ? "Enter an amount, like 250." : null;
  const lookupError =
    lookup.error?.code === "handle_not_found"
      ? `No one has the handle @${handle}.`
      : lookup.error?.message;

  function submit(event: FormEvent) {
    event.preventDefault();
    setTouched(true);
    if (!handle || self || cents === null) return;
    lookup.mutate(handle, {
      onSuccess: (found) =>
        onReady({ to: found.handle, cents, note: note.trim(), key: newIdempotencyKey("send") }),
    });
  }

  return (
    <>
      <PageTitle
        title="Send money"
        subtitle={
          balance.data ? (
            <>
              Available:{" "}
              <span className="font-semibold text-ink">
                {formatKes(balance.data.balance_cents)}
              </span>
            </>
          ) : (
            "Pay anyone with an X Money handle."
          )
        }
      />
      <form onSubmit={submit} className="flex flex-col gap-5" noValidate>
        <Card className="flex flex-col gap-4">
          <Field label="To" htmlFor="to" error={toError || lookupError}>
            <Input
              id="to"
              prefix="@"
              autoCapitalize="none"
              autoCorrect="off"
              spellCheck={false}
              placeholder="baraka"
              value={to}
              onChange={(e) => {
                setTo(e.target.value.replace(/^@/, ""));
                lookup.reset();
              }}
              aria-invalid={!!(toError || lookupError) || undefined}
            />
          </Field>
          <Field label="Amount" htmlFor="amount" error={amountError}>
            <Input
              id="amount"
              prefix="KES"
              inputMode="decimal"
              className="pl-16 text-xl font-semibold"
              placeholder="0"
              value={amount}
              onChange={(e) => setAmount(e.target.value)}
              aria-invalid={!!amountError || undefined}
            />
          </Field>
          <Field label="Note (optional)" htmlFor="note">
            <Input
              id="note"
              maxLength={140}
              placeholder="Lunch"
              value={note}
              onChange={(e) => setNote(e.target.value)}
            />
          </Field>
        </Card>
        <Button type="submit" loading={lookup.isPending}>
          Continue
        </Button>
      </form>
    </>
  );
}

function Confirm({
  draft,
  onBack,
  onSent,
}: {
  draft: Draft;
  onBack: () => void;
  onSent: (t: Transfer) => void;
}) {
  const send = useSend();
  return (
    <section className="flex flex-col gap-6" aria-label="Confirm send">
      <PageTitle title="Confirm send" subtitle="Check the handle. Sends can't be reversed." />
      <Card className="flex flex-col items-center gap-4 py-8 text-center">
        <span className="flex size-16 items-center justify-center rounded-full bg-ink text-2xl font-bold text-white uppercase">
          {draft.to.charAt(0)}
        </span>
        <div>
          <p className="text-sm text-muted">You&apos;re sending</p>
          <p
            className="text-3xl font-bold tracking-tight tabular-nums"
            data-testid="confirm-amount"
          >
            {formatKes(draft.cents)}
          </p>
          <p className="mt-1 text-base">
            to{" "}
            <span className="font-semibold" data-testid="confirm-recipient">
              @{draft.to}
            </span>
          </p>
        </div>
        {draft.note && (
          <p className="rounded-full bg-surface px-4 py-1.5 text-sm">“{draft.note}”</p>
        )}
      </Card>
      {send.error && (
        <Alert
          action={
            send.error.code === "insufficient_funds" ? (
              <ButtonLink href="/top-up/" variant="secondary" className="h-10">
                Top up
              </ButtonLink>
            ) : undefined
          }
        >
          {send.error.message}
        </Alert>
      )}
      <div className="flex flex-col gap-3">
        <Button
          loading={send.isPending}
          onClick={() =>
            send.mutate(
              {
                to: draft.to,
                amount_cents: draft.cents,
                note: draft.note || null,
                idempotencyKey: draft.key,
              },
              { onSuccess: onSent },
            )
          }
        >
          Send {formatKes(draft.cents)}
        </Button>
        <Button variant="secondary" onClick={onBack} disabled={send.isPending}>
          Edit
        </Button>
      </div>
    </section>
  );
}

function Sent({ transfer, onAgain }: { transfer: Transfer; onAgain: () => void }) {
  return (
    <section
      className="flex flex-col items-center gap-6 pt-6 text-center"
      aria-live="polite"
      data-testid="send-success"
    >
      <div className="flex size-24 items-center justify-center rounded-full bg-brand text-white">
        <CheckIcon className="size-12" />
      </div>
      <div className="flex flex-col gap-2">
        <h1 className="text-2xl font-bold tracking-tight">
          Sent {formatKes(transfer.amount_cents)}
        </h1>
        <p className="text-muted">
          @{transfer.recipient} has it now{transfer.note ? ` · “${transfer.note}”` : ""}.
        </p>
      </div>
      <div className="flex w-full flex-col gap-3">
        <ButtonLink href="/home/">Back to wallet</ButtonLink>
        <Button variant="secondary" onClick={onAgain}>
          Send to someone else
        </Button>
      </div>
    </section>
  );
}
