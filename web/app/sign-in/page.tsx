"use client";

import Link from "next/link";
import { useState, type FormEvent } from "react";

import { CodeStep } from "@/components/code-step";
import { PublicShell } from "@/components/public-shell";
import { Alert, Button, Field, Input, PageTitle } from "@/components/ui";
import { useStartSignIn } from "@/lib/api/hooks";
import { normalizeKenyanPhone } from "@/lib/format";

export default function SignIn() {
  const signIn = useStartSignIn();
  const [phone, setPhone] = useState("");
  const [pin, setPin] = useState("");
  const [touched, setTouched] = useState(false);
  const e164 = normalizeKenyanPhone(phone);
  const phoneError = touched && !e164 ? "Enter a Kenyan mobile number, like 0712 345 000." : null;
  const pinError = touched && !/^\d{4,6}$/.test(pin) ? "Your PIN is 4 to 6 digits." : null;

  function submit(event: FormEvent) {
    event.preventDefault();
    setTouched(true);
    if (!e164 || !/^\d{4,6}$/.test(pin)) return;
    signIn.mutate({ phone: e164, pin });
  }

  if (signIn.data && e164) {
    return (
      <PublicShell onBack={() => signIn.reset()}>
        <CodeStep challengeId={signIn.data.challenge_id} phone={e164} />
      </PublicShell>
    );
  }

  return (
    <PublicShell back="/">
      <PageTitle title="Welcome back" subtitle="Sign in with your phone number and PIN." />
      <form onSubmit={submit} className="flex flex-col gap-5" noValidate>
        <Field label="Phone number" htmlFor="phone" error={phoneError}>
          <Input
            id="phone"
            type="tel"
            inputMode="tel"
            autoComplete="tel"
            placeholder="0712 345 000"
            value={phone}
            onChange={(e) => setPhone(e.target.value)}
            aria-invalid={!!phoneError || undefined}
          />
        </Field>
        <Field label="PIN" htmlFor="pin" error={pinError}>
          <Input
            id="pin"
            type="password"
            inputMode="numeric"
            autoComplete="current-password"
            maxLength={6}
            value={pin}
            onChange={(e) => setPin(e.target.value.replace(/\D/g, ""))}
            aria-invalid={!!pinError || undefined}
          />
        </Field>
        {signIn.error && <Alert>{signIn.error.message}</Alert>}
        <Button type="submit" loading={signIn.isPending}>
          Continue
        </Button>
        <p className="text-center text-sm text-muted">
          New here?{" "}
          <Link href="/register/" className="font-semibold text-brand">
            Create a wallet
          </Link>
        </p>
      </form>
    </PublicShell>
  );
}
