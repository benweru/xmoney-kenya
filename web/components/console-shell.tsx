"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { createContext, useContext, useEffect, type ReactNode } from "react";

import type { StaffMe } from "@/lib/api/client";
import { useStaffMe, useStaffSignOut } from "@/lib/api/hooks";

import { Alert, Button, Skeleton, cx } from "./ui";

const StaffContext = createContext<StaffMe | null>(null);

export function useStaff(): StaffMe {
  const staff = useContext(StaffContext);
  if (!staff) throw new Error("useStaff must be used inside <ConsoleShell>");
  return staff;
}

const NAV = [
  { href: "/console/", label: "Home" },
  { href: "/console/users/", label: "Users" },
  { href: "/console/recon/", label: "Recon" },
  { href: "/console/suspense/", label: "Suspense" },
  { href: "/console/reversals/", label: "Reversals" },
  { href: "/console/dlq/", label: "DLQ" },
  { href: "/console/audit/", label: "Audit" },
] as const;

export function ConsoleShell({ children }: { children: ReactNode }) {
  const me = useStaffMe();
  const router = useRouter();

  useEffect(() => {
    if (me.data === null) router.replace("/console/sign-in/");
  }, [me.data, router]);

  if (me.isError) {
    return (
      <Frame>
        <main className="flex flex-1 flex-col justify-center gap-4 px-5 py-10">
          <Alert
            title="Can't load the console"
            action={
              <Button variant="secondary" onClick={() => me.refetch()}>
                Try again
              </Button>
            }
          >
            {me.error.message}
          </Alert>
        </main>
      </Frame>
    );
  }

  if (!me.data) {
    return (
      <Frame>
        <div className="flex flex-col gap-4 px-5 pt-6" aria-busy="true" aria-label="Loading">
          <Skeleton className="h-10 w-40" />
          <Skeleton className="h-40 w-full rounded-3xl" />
        </div>
      </Frame>
    );
  }

  return (
    <StaffContext.Provider value={me.data}>
      <Frame>
        <Header handle={me.data.handle} />
        <Nav />
        <main className="flex flex-1 flex-col gap-5 px-5 pt-4 pb-10">{children}</main>
      </Frame>
    </StaffContext.Provider>
  );
}

function Frame({ children }: { children: ReactNode }) {
  return <div className="mx-auto flex w-full max-w-3xl flex-1 flex-col">{children}</div>;
}

function Header({ handle }: { handle: string }) {
  const signOut = useStaffSignOut();
  const router = useRouter();
  return (
    <header className="flex items-center justify-between px-5 pt-5 pb-3">
      <div className="flex flex-col leading-tight">
        <span className="text-xs text-muted">Staff console · sandbox</span>
        <span className="font-semibold">@{handle}</span>
      </div>
      <button
        type="button"
        onClick={() =>
          signOut.mutate(undefined, { onSettled: () => router.replace("/console/sign-in/") })
        }
        className="text-sm font-semibold text-muted hover:text-ink"
      >
        Sign out
      </button>
    </header>
  );
}

function Nav() {
  const pathname = usePathname();
  return (
    <nav aria-label="Console" className="overflow-x-auto border-y border-line bg-white px-2">
      <ul className="flex min-w-max gap-1">
        {NAV.map(({ href, label }) => {
          const active = pathname === href || pathname === href.slice(0, -1);
          return (
            <li key={href}>
              <Link
                href={href}
                aria-current={active ? "page" : undefined}
                className={cx(
                  "inline-flex h-11 items-center px-3 text-sm font-medium",
                  active ? "text-brand" : "text-muted hover:text-ink",
                )}
              >
                {label}
              </Link>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}
