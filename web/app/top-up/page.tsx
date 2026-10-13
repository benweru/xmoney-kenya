"use client";

import { useEffect, useRef, useState, type FormEvent } from "react";

import { SignedInShell, useSignedInUser } from "@/components/app-shell";
import { CheckIcon, CrossIcon, PhoneIcon } from "@/components/icons";
import { Alert, Button, ButtonLink, Card, Field, Input, PageTitle, cx } from "@/components/ui";
import type { Topup } from "@/lib/api/client";
import { newIdempotencyKey, useStartTopup, useTopupStatus } from "@/lib/api/hooks";
import { formatKes, formatPhone, normalizeKenyanPhone, parseKesToCents } from "@/lib/format";

const PRESETS = [100, 500, 1000] as const;

export default function TopUpPage() {
  return (
    <SignedInShell>
      <TopUp />
    </SignedInShell>
  );
}

function TopUp() {
  const me = useSignedInUser();
  const start = useStartTopup();
  const [amount, setAmount] = useState("500");
  const [otherPhone, setOtherPhone] = useState<string | null>(null);
  const [touched, setTouched] = useState(false);
  const [topupId, setTopupId] = useState<string | null>(null);
  const key = useRef<string | null>(null);

  const cents = parseKesToCents(amount);
  const amountError =
    touched && (cents === null || cents % 100 !== 0) ? "Enter a whole number of shillings." : null;
  const phone = otherPhone === null ? me.phone : normalizeKenyanPhone(otherPhone);
  const phoneError = touched && !phone ? "Enter a Kenyan mobile number." : null;

  function submit(event: FormEvent) {
    event.preventDefault();
    setTouched(true);
    if (cents === null || cents % 100 !== 0 || !phone) return;
    key.current ??= newIdempotencyKey("topup");
    start.mutate(
      { amount_cents: cents, phone, idempotencyKey: key.current },
      {
        onSuccess: (topup) => {
          key.current = null;
          setTopupId(topup.id);
        },
      },
    );
  }

  function changed() {
    key.current = null;
    start.reset();
  }

  if (topupId) {
    return (
      <TopupStatus
        id={topupId}
        onAgain={() => {
          setTopupId(null);
          start.reset();
        }}
      />
    );
  }

  return (
    <>
      <PageTitle title="Top up" subtitle="We'll send an M-PESA prompt to your phone." />
      <form onSubmit={submit} className="flex flex-col gap-5" noValidate>
        <Card className="flex flex-col gap-4">
          <Field label="Amount" htmlFor="amount" error={amountError}>
            <Input
              id="amount"
              prefix="KES"
              inputMode="decimal"
              className="pl-16 text-2xl font-semibold"
              value={amount}
              onChange={(e) => {
                setAmount(e.target.value);
                changed();
              }}
              aria-invalid={!!amountError || undefined}
            />
          </Field>
          <div className="flex gap-2" role="group" aria-label="Quick amounts">
            {PRESETS.map((preset) => (
              <button
                key={preset}
                type="button"
                onClick={() => {
                  setAmount(String(preset));
                  changed();
                }}
                className={cx(
                  "h-10 flex-1 rounded-full border text-sm font-semibold",
                  cents === preset * 100
                    ? "border-brand bg-brand-soft text-brand-strong"
                    : "border-line bg-white hover:border-brand/40",
                )}
              >
                {preset.toLocaleString("en-KE")}
              </button>
            ))}
          </div>
        </Card>

        <Card className="flex flex-col gap-3">
          {otherPhone === null ? (
            <div className="flex items-center justify-between gap-3">
              <div className="flex min-w-0 items-center gap-3">
                <span className="flex size-10 shrink-0 items-center justify-center rounded-full bg-surface">
                  <PhoneIcon className="size-5" />
                </span>
                <span className="flex min-w-0 flex-col">
                  <span className="text-xs text-muted">M-PESA number</span>
                  <span className="font-medium whitespace-nowrap">{formatPhone(me.phone)}</span>
                </span>
              </div>
              <Button
                type="button"
                variant="ghost"
                className="h-9 w-auto px-3 text-sm"
                onClick={() => setOtherPhone("")}
              >
                Change
              </Button>
            </div>
          ) : (
            <Field
              label="Pay from another M-PESA number"
              htmlFor="phone"
              error={phoneError}
              hint={
                <>
                  Mock outcomes: <span className="font-mono">…000</span> pays,{" "}
                  <span className="font-mono">…032</span> is cancelled,{" "}
                  <span className="font-mono">…001</span> has no funds.
                </>
              }
            >
              <Input
                id="phone"
                type="tel"
                inputMode="tel"
                placeholder="0712 345 000"
                value={otherPhone}
                onChange={(e) => {
                  setOtherPhone(e.target.value);
                  changed();
                }}
                aria-invalid={!!phoneError || undefined}
              />
            </Field>
          )}
        </Card>

        {start.error && <Alert>{start.error.message}</Alert>}
        <Button type="submit" loading={start.isPending}>
          {cents ? `Top up ${formatKes(cents)}` : "Top up"}
        </Button>
      </form>
    </>
  );
}

function TopupStatus({ id, onAgain }: { id: string; onAgain: () => void }) {
  const status = useTopupStatus(id);
  const topup = status.data;

  if (status.isError && !topup) {
    return (
      <Alert
        title="Can't check this top-up"
        action={
          <Button variant="secondary" onClick={() => status.refetch()}>
            Check again
          </Button>
        }
      >
        {status.error.message}
      </Alert>
    );
  }
  if (!topup || topup.status === "initiated" || topup.status === "pending") {
    return <Waiting topup={topup} />;
  }
  if (topup.status === "succeeded") {
    return (
      <Outcome
        tone="success"
        title={`${formatKes(topup.amount_cents)} added`}
        body={
          <>
            M-PESA receipt{" "}
            <span className="font-mono font-medium text-ink">{topup.mpesa_receipt_number}</span>
          </>
        }
        onAgain={onAgain}
      />
    );
  }
  if (topup.status === "expired") {
    return (
      <Outcome
        tone="warn"
        title="We didn't hear back from M-PESA"
        body="If you approved the prompt, your wallet is credited as soon as M-PESA confirms."
        onAgain={onAgain}
      />
    );
  }
  return (
    <Outcome
      tone="danger"
      title="Top-up didn't go through"
      body={topup.result_desc ?? "M-PESA declined the payment. No money moved."}
      onAgain={onAgain}
    />
  );
}

function Waiting({ topup }: { topup: Topup | undefined }) {
  const [seconds, setSeconds] = useState(0);
  useEffect(() => {
    const timer = setInterval(() => setSeconds((s) => s + 1), 1_000);
    return () => clearInterval(timer);
  }, []);
  return (
    <section
      className="flex flex-col items-center gap-6 pt-6 text-center"
      aria-live="polite"
      data-testid="topup-waiting"
    >
      <div className="ripple relative flex size-24 items-center justify-center rounded-full bg-brand-soft text-brand">
        <PhoneIcon className="size-10" />
      </div>
      <div className="flex flex-col gap-2">
        <h1 className="text-2xl font-bold tracking-tight">Check your phone</h1>
        <p className="text-muted">
          {topup ? (
            <>
              Enter your M-PESA PIN on the prompt for{" "}
              <span className="font-semibold text-ink">{formatKes(topup.amount_cents)}</span> sent
              to {formatPhone(topup.phone)}.
            </>
          ) : (
            "Sending the M-PESA prompt…"
          )}
        </p>
      </div>
      <p className="rounded-full bg-white px-4 py-2 text-sm font-medium text-muted">
        Waiting for M-PESA · {seconds}s
      </p>
      <p className="max-w-xs text-xs text-muted">
        On the mock, the prompt is approved for you. If a callback goes missing, we ask M-PESA
        directly after a minute.
      </p>
    </section>
  );
}

function Outcome({
  tone,
  title,
  body,
  onAgain,
}: {
  tone: "success" | "warn" | "danger";
  title: string;
  body: React.ReactNode;
  onAgain: () => void;
}) {
  const styles = {
    success: "bg-brand text-white",
    warn: "bg-warn-soft text-warn",
    danger: "bg-danger-soft text-danger",
  } as const;
  return (
    <section
      className="flex flex-col items-center gap-6 pt-6 text-center"
      aria-live="polite"
      data-testid={`topup-${tone}`}
    >
      <div className={cx("flex size-24 items-center justify-center rounded-full", styles[tone])}>
        {tone === "success" ? <CheckIcon className="size-12" /> : <CrossIcon className="size-12" />}
      </div>
      <div className="flex flex-col gap-2">
        <h1 className="text-2xl font-bold tracking-tight">{title}</h1>
        <p className="text-muted">{body}</p>
      </div>
      <div className="flex w-full flex-col gap-3">
        <ButtonLink href="/home/">Back to wallet</ButtonLink>
        <Button variant="secondary" onClick={onAgain}>
          {tone === "success" ? "Top up again" : "Try again"}
        </Button>
      </div>
    </section>
  );
}
