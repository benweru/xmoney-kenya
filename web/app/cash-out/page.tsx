"use client";

import { useRef, useState, type FormEvent } from "react";

import { SignedInShell, useSignedInUser } from "@/components/app-shell";
import { CheckIcon, CrossIcon } from "@/components/icons";
import { Alert, Button, ButtonLink, Card, Field, Input, PageTitle, cx } from "@/components/ui";
import type { Rail, Rails } from "@/lib/api/client";
import {
  newIdempotencyKey,
  useBalance,
  useCashoutStatus,
  useRails,
  useStartCashout,
} from "@/lib/api/hooks";
import { formatKes, formatPhone, normalizeKenyanPhone, parseKesToCents } from "@/lib/format";

const PRESETS = [100, 500, 1000] as const;

export default function CashOutPage() {
  return (
    <SignedInShell>
      <CashOut />
    </SignedInShell>
  );
}

function CashOut() {
  const me = useSignedInUser();
  const balance = useBalance();
  const start = useStartCashout();
  const rails = useRails();
  const [chosenRail, setChosenRail] = useState<Rail | null>(null);
  const [amount, setAmount] = useState("100");
  const [otherPhone, setOtherPhone] = useState<string | null>(null);
  const [touched, setTouched] = useState(false);
  const [cashoutId, setCashoutId] = useState<string | null>(null);
  const key = useRef<string | null>(null);

  const cents = parseKesToCents(amount);
  const available = balance.data?.balance_cents ?? 0;
  const amountError =
    touched && (cents === null || cents % 100 !== 0)
      ? "Enter a whole number of shillings."
      : touched && cents !== null && cents > available
        ? "That is more than your balance."
        : null;
  const phone = otherPhone === null ? me.phone : normalizeKenyanPhone(otherPhone);
  const phoneError = touched && !phone ? "Enter a Kenyan mobile number." : null;
  const rail = chosenRail ?? (rails.data?.default as Rail | undefined) ?? "mock";

  function submit(event: FormEvent) {
    event.preventDefault();
    setTouched(true);
    if (cents === null || cents % 100 !== 0 || !phone || cents > available) return;
    key.current ??= newIdempotencyKey("cashout");
    start.mutate(
      { amount_cents: cents, phone, rail, idempotencyKey: key.current },
      {
        onSuccess: (cashout) => {
          key.current = null;
          setCashoutId(cashout.id);
        },
      },
    );
  }

  function changed() {
    key.current = null;
    start.reset();
  }

  if (cashoutId) {
    return (
      <CashoutStatus
        id={cashoutId}
        onAgain={() => {
          setCashoutId(null);
          start.reset();
        }}
      />
    );
  }

  return (
    <>
      <PageTitle title="Cash out" subtitle="We'll send shillings to your M-PESA." />
      <form onSubmit={submit} className="flex flex-col gap-5" noValidate>
        <Card className="flex flex-col gap-4">
          <p className="text-sm text-muted">
            Available{" "}
            <span className="font-semibold text-ink">
              {balance.data ? formatKes(balance.data.balance_cents) : "…"}
            </span>
          </p>
          <Field label="Amount" htmlFor="amount" error={amountError}>
            <Input
              id="amount"
              inputMode="numeric"
              value={amount}
              onChange={(event) => {
                setAmount(event.target.value);
                changed();
              }}
              aria-invalid={!!amountError}
            />
          </Field>
          <div className="flex gap-2">
            {PRESETS.map((kes) => (
              <button
                key={kes}
                type="button"
                className={cx(
                  "flex-1 rounded-full border py-2 text-sm font-semibold",
                  amount === String(kes) ? "border-brand bg-brand-soft text-brand" : "border-line",
                )}
                onClick={() => {
                  setAmount(String(kes));
                  changed();
                }}
              >
                {formatKes(kes * 100)}
              </button>
            ))}
          </div>
          <Field label="M-PESA number" htmlFor="phone" error={phoneError}>
            <Input
              id="phone"
              inputMode="tel"
              autoComplete="tel"
              value={otherPhone === null ? formatPhone(me.phone) : otherPhone}
              onChange={(event) => {
                setOtherPhone(event.target.value);
                changed();
              }}
              aria-invalid={!!phoneError}
            />
          </Field>
          {rails.data && rails.data.rails.length > 1 && (
            <RailPicker rails={rails.data} value={rail} onChange={setChosenRail} />
          )}
        </Card>
        {start.isError && <Alert>{start.error.message}</Alert>}
        <Button type="submit" disabled={start.isPending}>
          {start.isPending ? "Holding funds…" : cents ? `Cash out ${formatKes(cents)}` : "Cash out"}
        </Button>
      </form>
    </>
  );
}

function RailPicker({
  rails,
  value,
  onChange,
}: {
  rails: Rails;
  value: Rail;
  onChange: (rail: Rail) => void;
}) {
  const selected = rails.rails.find((option) => option.name === value);
  return (
    <fieldset>
      <legend className="mb-2 text-sm font-medium">Payment rail</legend>
      <div className="grid grid-cols-2 gap-1 rounded-full border border-line bg-white p-1">
        {rails.rails.map((option) => (
          <label
            key={option.name}
            className={cx(
              "flex h-10 cursor-pointer items-center justify-center rounded-full text-sm font-semibold",
              option.name === value ? "bg-brand text-white" : "text-muted hover:text-ink",
            )}
          >
            <input
              type="radio"
              name="rail"
              value={option.name}
              checked={option.name === value}
              onChange={() => onChange(option.name as Rail)}
              className="sr-only"
            />
            {option.name === "mock" ? "Mock" : "Daraja sandbox"}
          </label>
        ))}
      </div>
      <p className="text-xs text-muted">
        {value === "mock"
          ? "The built-in Daraja mock pays instantly. Outcomes follow the phone's last digits."
          : selected?.restricted
            ? "Safaricom's sandbox. Limited to the demo owner's test phones."
            : "Safaricom's sandbox B2C. No live money moves."}
      </p>
    </fieldset>
  );
}

function CashoutStatus({ id, onAgain }: { id: string; onAgain: () => void }) {
  const status = useCashoutStatus(id);
  const cashout = status.data;

  if (status.isError && !cashout) {
    return (
      <Alert
        title="Can't check this cash-out"
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
  if (!cashout || cashout.status === "initiated" || cashout.status === "pending") {
    return (
      <section
        className="flex flex-col items-center gap-6 pt-6 text-center"
        aria-live="polite"
        data-testid="cashout-waiting"
      >
        <div className="ripple relative flex size-24 items-center justify-center rounded-full bg-brand-soft text-brand">
          <span className="text-3xl font-bold">KES</span>
        </div>
        <div className="flex flex-col gap-2">
          <h1 className="text-2xl font-bold tracking-tight">Sending to M-PESA</h1>
          <p className="text-muted">
            {cashout ? (
              <>
                {formatKes(cashout.amount_cents)} is on hold. Paying {formatPhone(cashout.phone)}.
              </>
            ) : (
              "Holding the amount and queuing B2C…"
            )}
          </p>
        </div>
      </section>
    );
  }
  if (cashout.status === "succeeded") {
    return (
      <Outcome
        tone="success"
        title={`${formatKes(cashout.amount_cents)} sent`}
        body={
          <>
            M-PESA receipt{" "}
            <span className="font-mono font-medium text-ink">{cashout.mpesa_receipt_number}</span>
          </>
        }
        onAgain={onAgain}
      />
    );
  }
  if (cashout.status === "expired") {
    return (
      <Outcome
        tone="warn"
        title="M-PESA has not confirmed yet"
        body="The amount stays on hold. If the payment went through, we will settle it when M-PESA answers."
        onAgain={onAgain}
      />
    );
  }
  return (
    <Outcome
      tone="danger"
      title="Cash-out didn't go through"
      body={cashout.result_desc ?? "The hold was returned to your wallet."}
      onAgain={onAgain}
    />
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
      data-testid={`cashout-${tone}`}
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
          {tone === "success" ? "Cash out again" : "Try again"}
        </Button>
      </div>
    </section>
  );
}
