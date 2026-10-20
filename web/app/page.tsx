"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect } from "react";

import { ShieldIcon, SendIcon, TopUpIcon } from "@/components/icons";
import { PublicShell } from "@/components/public-shell";
import { ButtonLink } from "@/components/ui";
import { useMe } from "@/lib/api/hooks";

const FEATURES = [
  {
    icon: TopUpIcon,
    title: "Top up from M-PESA",
    body: "An STK prompt on your phone, then your balance updates the moment M-PESA confirms.",
  },
  {
    icon: SendIcon,
    title: "Send to an @handle",
    body: "Pay @amina instead of typing a phone number. Every send happens exactly once.",
  },
  {
    icon: ShieldIcon,
    title: "Built like a real wallet",
    body: "A double-entry ledger in Postgres that cannot be unbalanced, and no overdrafts.",
  },
] as const;

export default function Welcome() {
  const me = useMe();
  const router = useRouter();
  useEffect(() => {
    if (me.data) router.replace("/home/");
  }, [me.data, router]);

  return (
    <PublicShell>
      <section className="flex flex-col gap-4 pt-4">
        <p className="w-fit rounded-full bg-brand-soft px-3 py-1 text-xs font-semibold text-brand-strong">
          Sandbox demo · KES
        </p>
        <h1 className="text-4xl leading-[1.05] font-extrabold tracking-tight">
          Pay anyone in Kenya by <span className="text-brand">@handle</span>.
        </h1>
        <p className="text-base text-muted">
          Top up from M-PESA, send to a handle, and see every shilling in your history. Try it with
          a test number. Nothing here moves real money.
        </p>
      </section>

      <div className="flex flex-col gap-3">
        <ButtonLink href="/register/">Create a wallet</ButtonLink>
        <ButtonLink href="/sign-in/" variant="secondary">
          I already have one
        </ButtonLink>
      </div>

      <ul className="flex flex-col gap-3">
        {FEATURES.map(({ icon: FeatureIcon, title, body }) => (
          <li key={title} className="flex gap-4 rounded-3xl border border-line bg-white p-4">
            <span className="flex size-10 shrink-0 items-center justify-center rounded-2xl bg-brand-soft text-brand">
              <FeatureIcon className="size-5" />
            </span>
            <span className="flex flex-col gap-0.5">
              <span className="font-semibold">{title}</span>
              <span className="text-sm text-muted">{body}</span>
            </span>
          </li>
        ))}
      </ul>
      <p className="text-center text-sm text-muted">
        Staff?{" "}
        <Link href="/console/sign-in/" className="font-semibold text-brand">
          Open the operations console
        </Link>
      </p>
    </PublicShell>
  );
}
