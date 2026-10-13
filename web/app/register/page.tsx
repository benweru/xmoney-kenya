"use client";

import Link from "next/link";
import { useState, type FormEvent } from "react";

import { CodeStep } from "@/components/code-step";
import { PublicShell } from "@/components/public-shell";
import { Alert, Button, Field, Input, PageTitle } from "@/components/ui";
import { useRegister, useStartSignIn } from "@/lib/api/hooks";
import { normalizeHandle, normalizeKenyanPhone } from "@/lib/format";

const HANDLE_RE = /^[a-z][a-z0-9_]{2,19}$/;
const PIN_RE = /^\d{4,6}$/;

type Errors = Partial<Record<"handle" | "phone" | "pin" | "confirm", string>>;

function validate(handle: string, phone: string, pin: string, confirm: string): Errors {
  const errors: Errors = {};
  if (!HANDLE_RE.test(normalizeHandle(handle))) {
    errors.handle = "3–20 letters, digits, or underscores, starting with a letter.";
  }
  if (!normalizeKenyanPhone(phone))
    errors.phone = "Enter a Kenyan mobile number, like 0712 345 000.";
  if (!PIN_RE.test(pin)) errors.pin = "Use 4 to 6 digits.";
  else if (confirm !== pin) errors.confirm = "The PINs don't match.";
  return errors;
}

export default function Register() {
  const register = useRegister();
  const signIn = useStartSignIn();
  const [handle, setHandle] = useState("");
  const [phone, setPhone] = useState("");
  const [pin, setPin] = useState("");
  const [confirm, setConfirm] = useState("");
  const [touched, setTouched] = useState(false);
  const errors = touched ? validate(handle, phone, pin, confirm) : {};
  const serverError = register.error ?? signIn.error;

  function submit(event: FormEvent) {
    event.preventDefault();
    setTouched(true);
    if (Object.keys(validate(handle, phone, pin, confirm)).length > 0) return;
    const e164 = normalizeKenyanPhone(phone)!;
    register.mutate(
      { handle: normalizeHandle(handle), phone: e164, pin },
      { onSuccess: () => signIn.mutate({ phone: e164, pin }) },
    );
  }

  if (signIn.data) {
    return (
      <PublicShell onBack={() => signIn.reset()}>
        <CodeStep challengeId={signIn.data.challenge_id} phone={normalizeKenyanPhone(phone)!} />
      </PublicShell>
    );
  }

  return (
    <PublicShell back="/">
      <PageTitle
        title="Create your wallet"
        subtitle="Pick a handle people can pay, and a PIN only you know."
      />
      <form onSubmit={submit} className="flex flex-col gap-5" noValidate>
        <Field
          label="Handle"
          htmlFor="handle"
          error={errors.handle}
          hint="Friends send to this, like @amina."
        >
          <Input
            id="handle"
            prefix="@"
            autoCapitalize="none"
            autoCorrect="off"
            spellCheck={false}
            placeholder="amina"
            value={handle}
            onChange={(e) => setHandle(e.target.value.replace(/^@/, ""))}
            aria-invalid={!!errors.handle || undefined}
          />
        </Field>
        <Field
          label="M-PESA phone number"
          htmlFor="phone"
          error={errors.phone}
          hint={
            <>
              On the mock, a number ending in <span className="font-mono">000</span> pays instantly.
            </>
          }
        >
          <Input
            id="phone"
            type="tel"
            inputMode="tel"
            autoComplete="tel"
            placeholder="0712 345 000"
            value={phone}
            onChange={(e) => setPhone(e.target.value)}
            aria-invalid={!!errors.phone || undefined}
          />
        </Field>
        <div className="grid grid-cols-2 gap-3">
          <Field label="PIN" htmlFor="pin" error={errors.pin}>
            <Input
              id="pin"
              type="password"
              inputMode="numeric"
              autoComplete="new-password"
              maxLength={6}
              placeholder="4–6 digits"
              value={pin}
              onChange={(e) => setPin(e.target.value.replace(/\D/g, ""))}
              aria-invalid={!!errors.pin || undefined}
            />
          </Field>
          <Field label="Confirm PIN" htmlFor="confirm" error={errors.confirm}>
            <Input
              id="confirm"
              type="password"
              inputMode="numeric"
              autoComplete="new-password"
              maxLength={6}
              value={confirm}
              onChange={(e) => setConfirm(e.target.value.replace(/\D/g, ""))}
              aria-invalid={!!errors.confirm || undefined}
            />
          </Field>
        </div>
        <p className="-mt-2 text-xs text-muted">
          Avoid easy PINs like 1234 or 1111; they&apos;re refused.
        </p>
        {serverError && <Alert>{serverError.message}</Alert>}
        <Button type="submit" loading={register.isPending || signIn.isPending}>
          Create wallet
        </Button>
        <p className="text-center text-sm text-muted">
          Have a wallet?{" "}
          <Link href="/sign-in/" className="font-semibold text-brand">
            Sign in
          </Link>
        </p>
      </form>
    </PublicShell>
  );
}
