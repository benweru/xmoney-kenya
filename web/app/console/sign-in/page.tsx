"use client";

import { useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";

import { PublicShell } from "@/components/public-shell";
import { Alert, Button, Field, Input, PageTitle } from "@/components/ui";
import { useStaffSignIn } from "@/lib/api/hooks";
import { normalizeHandle } from "@/lib/format";

export default function ConsoleSignIn() {
  const router = useRouter();
  const signIn = useStaffSignIn();
  const [handle, setHandle] = useState("ops");
  const [pin, setPin] = useState("");
  const [touched, setTouched] = useState(false);
  const normalized = normalizeHandle(handle);
  const handleError =
    touched && !/^[a-z][a-z0-9_]{2,19}$/.test(normalized)
      ? "Staff handle is 3–20 letters, digits, or underscores."
      : null;
  const pinError = touched && !/^\d{4,6}$/.test(pin) ? "PIN is 4 to 6 digits." : null;

  function submit(event: FormEvent) {
    event.preventDefault();
    setTouched(true);
    if (!/^[a-z][a-z0-9_]{2,19}$/.test(normalized) || !/^\d{4,6}$/.test(pin)) return;
    signIn.mutate({ handle: normalized, pin }, { onSuccess: () => router.replace("/console/") });
  }

  return (
    <PublicShell back="/">
      <PageTitle
        title="Staff console"
        subtitle="Separate from wallet sign-in. Demo seed is @ops / 2580. Local console can apply, refund, and reverse; a public https demo cannot."
      />
      <form onSubmit={submit} className="flex flex-col gap-5" noValidate>
        <Field label="Handle" htmlFor="handle" error={handleError}>
          <Input
            id="handle"
            prefix="@"
            autoComplete="username"
            value={handle}
            onChange={(e) => setHandle(e.target.value)}
            aria-invalid={!!handleError || undefined}
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
          Sign in
        </Button>
      </form>
    </PublicShell>
  );
}
