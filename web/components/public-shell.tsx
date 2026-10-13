import Link from "next/link";
import type { ReactNode } from "react";

import { BackIcon } from "./icons";
import { Disclaimer } from "./sandbox-banner";

export function Logo({ className = "" }: { className?: string }) {
  return (
    <span className={`inline-flex items-center gap-2 ${className}`}>
      <span className="flex size-9 items-center justify-center rounded-xl bg-ink text-lg font-black text-white">
        X
      </span>
      <span className="text-lg font-bold tracking-tight">
        Money <span className="font-medium text-muted">Kenya</span>
      </span>
    </span>
  );
}

export function PublicShell({
  children,
  back,
  onBack,
}: {
  children: ReactNode;
  back?: string;
  onBack?: () => void;
}) {
  const backClass =
    "-ml-2 flex size-10 items-center justify-center rounded-full text-muted hover:bg-white hover:text-ink";
  return (
    <div className="mx-auto flex w-full max-w-md flex-1 flex-col px-5 pt-5 pb-8">
      <header className="flex h-12 items-center justify-between">
        {onBack ? (
          <button type="button" onClick={onBack} className={backClass} aria-label="Back">
            <BackIcon className="size-5" />
          </button>
        ) : back ? (
          <Link href={back} className={backClass} aria-label="Back">
            <BackIcon className="size-5" />
          </Link>
        ) : (
          <Logo />
        )}
      </header>
      <main className="flex flex-1 flex-col gap-6 pt-4">{children}</main>
      <footer className="pt-8">
        <Disclaimer />
      </footer>
    </div>
  );
}
