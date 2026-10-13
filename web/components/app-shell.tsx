"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { createContext, useContext, useEffect, type ReactNode } from "react";

import type { Me } from "@/lib/api/client";
import { useMe, useSignOut } from "@/lib/api/hooks";

import { HistoryIcon, HomeIcon, InboxIcon, LogOutIcon, SendIcon, TopUpIcon } from "./icons";
import { Alert, Button, Skeleton, cx } from "./ui";

const MeContext = createContext<Me | null>(null);

export function useSignedInUser(): Me {
  const me = useContext(MeContext);
  if (!me) throw new Error("useSignedInUser must be used inside <SignedInShell>");
  return me;
}

const NAV = [
  { href: "/home/", label: "Home", icon: HomeIcon },
  { href: "/send/", label: "Send", icon: SendIcon },
  { href: "/top-up/", label: "Top up", icon: TopUpIcon },
  { href: "/history/", label: "History", icon: HistoryIcon },
] as const;

/** Wallet pages: waits for the session, sends visitors without one to sign-in. */
export function SignedInShell({ children }: { children: ReactNode }) {
  const me = useMe();
  const router = useRouter();

  useEffect(() => {
    if (me.data === null) router.replace("/sign-in/");
  }, [me.data, router]);

  if (me.isError) {
    return (
      <Frame>
        <main className="flex flex-1 flex-col justify-center gap-4 px-5">
          <Alert
            title="Can't load your wallet"
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
          <Skeleton className="h-24 w-full rounded-3xl" />
        </div>
      </Frame>
    );
  }

  return (
    <MeContext.Provider value={me.data}>
      <Frame>
        <Header me={me.data} />
        <main className="flex flex-1 flex-col gap-5 px-5 pt-2 pb-28">{children}</main>
        <BottomNav />
      </Frame>
    </MeContext.Provider>
  );
}

function Frame({ children }: { children: ReactNode }) {
  return <div className="mx-auto flex w-full max-w-md flex-1 flex-col">{children}</div>;
}

function Header({ me }: { me: Me }) {
  const signOut = useSignOut();
  const router = useRouter();
  return (
    <header className="flex items-center justify-between px-5 pt-5 pb-3">
      <Link href="/home/" className="flex items-center gap-3" aria-label="Home">
        <span className="flex size-10 items-center justify-center rounded-full bg-ink text-base font-bold text-white uppercase">
          {me.handle.charAt(0)}
        </span>
        <span className="flex flex-col leading-tight">
          <span className="text-xs text-muted">Signed in as</span>
          <span className="font-semibold" data-testid="handle">
            @{me.handle}
          </span>
        </span>
      </Link>
      <div className="flex items-center gap-1">
        <Link
          href="/inbox/"
          className="flex size-10 items-center justify-center rounded-full text-muted hover:bg-white hover:text-ink"
          aria-label="Sandbox inbox"
          title="Sandbox inbox"
        >
          <InboxIcon className="size-5" />
        </Link>
        <button
          type="button"
          onClick={() => signOut.mutate(undefined, { onSettled: () => router.replace("/") })}
          className="flex size-10 items-center justify-center rounded-full text-muted hover:bg-white hover:text-ink"
          aria-label="Sign out"
          title="Sign out"
        >
          <LogOutIcon className="size-5" />
        </button>
      </div>
    </header>
  );
}

function BottomNav() {
  const pathname = usePathname();
  return (
    <nav
      aria-label="Wallet"
      className="fixed inset-x-0 bottom-0 z-10 border-t border-line bg-white/95 pb-[env(safe-area-inset-bottom)] backdrop-blur"
    >
      <ul className="mx-auto grid max-w-md grid-cols-4">
        {NAV.map(({ href, label, icon: NavIcon }) => {
          const active = pathname === href || pathname === href.slice(0, -1);
          return (
            <li key={href}>
              <Link
                href={href}
                aria-current={active ? "page" : undefined}
                className={cx(
                  "flex h-16 flex-col items-center justify-center gap-1 text-xs font-medium",
                  active ? "text-brand" : "text-muted hover:text-ink",
                )}
              >
                <NavIcon className="size-5" />
                {label}
              </Link>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}
