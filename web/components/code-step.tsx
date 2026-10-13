"use client";

import { useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";

import { useInbox, useVerifySignIn } from "@/lib/api/hooks";
import { formatPhone } from "@/lib/format";

import { InboxIcon } from "./icons";
import { Alert, Button, Field, Input, PageTitle, Skeleton } from "./ui";

const CODE_RE = /code is (\d{6})/;

/** Second sign-in step: the 6-digit code, with the sandbox inbox standing in for SMS. */
export function CodeStep({ challengeId, phone }: { challengeId: string; phone: string }) {
  const router = useRouter();
  const verify = useVerifySignIn();
  const [code, setCode] = useState("");
  const inbox = useInbox(phone);
  const latest = inbox.data?.[0];
  const sandboxCode = latest ? CODE_RE.exec(latest.body)?.[1] : undefined;

  function submit(event: FormEvent) {
    event.preventDefault();
    verify.mutate(
      { challenge_id: challengeId, code },
      { onSuccess: () => router.replace("/home/") },
    );
  }

  return (
    <form onSubmit={submit} className="flex flex-col gap-6" noValidate>
      <PageTitle
        title="Enter your code"
        subtitle={
          <>
            We sent a 6-digit code to{" "}
            <span className="font-medium text-ink">{formatPhone(phone)}</span>. It expires in 5
            minutes.
          </>
        }
      />

      <section
        aria-label="Sandbox inbox"
        className="rounded-3xl border border-dashed border-brand/40 bg-brand-soft/60 p-4"
      >
        <div className="flex items-center gap-2 text-sm font-semibold text-brand-strong">
          <InboxIcon className="size-4" />
          Sandbox inbox
        </div>
        <p className="mt-1 text-xs text-muted">
          The demo doesn&apos;t send SMS. Codes for this number land here instead.
        </p>
        <div className="mt-3">
          {sandboxCode ? (
            <div className="flex items-center justify-between gap-3 rounded-2xl bg-white px-4 py-3">
              <span
                className="font-mono text-2xl font-semibold tracking-[0.3em]"
                data-testid="inbox-code"
              >
                {sandboxCode}
              </span>
              <Button
                type="button"
                variant="ghost"
                className="h-10 w-auto px-3"
                onClick={() => setCode(sandboxCode)}
              >
                Use code
              </Button>
            </div>
          ) : inbox.isError ? (
            <p className="text-sm text-danger">{inbox.error.message}</p>
          ) : (
            <Skeleton className="h-14 w-full rounded-2xl" />
          )}
        </div>
      </section>

      <Field label="One-time code" htmlFor="code" error={verify.error?.message}>
        <Input
          id="code"
          name="code"
          inputMode="numeric"
          autoComplete="one-time-code"
          pattern="\d{6}"
          maxLength={6}
          placeholder="••••••"
          className="text-center font-mono text-2xl tracking-[0.4em]"
          value={code}
          onChange={(event) => setCode(event.target.value.replace(/\D/g, "").slice(0, 6))}
          aria-invalid={!!verify.error || undefined}
          autoFocus
        />
      </Field>

      <Button type="submit" loading={verify.isPending} disabled={code.length !== 6}>
        Verify and continue
      </Button>
      {verify.error?.code === "invalid_otp" && (
        <Alert tone="warn">
          After 5 wrong guesses the code stops working. Go back to get a new one.
        </Alert>
      )}
    </form>
  );
}
