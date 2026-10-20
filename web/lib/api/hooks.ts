"use client";

import {
  useInfiniteQuery,
  useMutation,
  useQuery,
  useQueryClient,
  type QueryClient,
} from "@tanstack/react-query";

import {
  api,
  ApiError,
  newIdempotencyKey,
  unwrap,
  type Cashout,
  type Me,
  type Rail,
  type StaffMe,
  type Topup,
} from "./client";

declare module "@tanstack/react-query" {
  interface Register {
    defaultError: ApiError;
  }
}

export const keys = {
  me: ["me"] as const,
  balance: ["balance"] as const,
  history: ["history"] as const,
  topup: (id: string) => ["topup", id] as const,
  cashout: (id: string) => ["cashout", id] as const,
  rails: ["rails"] as const,
  inbox: (phone: string) => ["inbox", phone] as const,
  staffMe: ["staff-me"] as const,
  consoleUser: (handle: string) => ["console-user", handle] as const,
  consoleLedger: (userId: string) => ["console-ledger", userId] as const,
  consoleJournal: (entryId: string) => ["console-journal", entryId] as const,
  consoleRecon: ["console-recon"] as const,
  consoleSuspense: ["console-suspense"] as const,
  consoleDlq: ["console-dlq"] as const,
  consoleAudit: ["console-audit"] as const,
};

/** The signed-in user, or null when there is no session. Other errors still throw. */
export function useMe() {
  return useQuery({
    queryKey: keys.me,
    queryFn: async (): Promise<Me | null> => {
      try {
        return await unwrap(api.GET("/v1/me"));
      } catch (error) {
        if (error instanceof ApiError && error.status === 401) return null;
        throw error;
      }
    },
    staleTime: 60_000,
  });
}

export function useBalance() {
  return useQuery({
    queryKey: keys.balance,
    queryFn: () => unwrap(api.GET("/v1/me/balance")),
  });
}

export function useHistory(pageSize = 20) {
  return useInfiniteQuery({
    queryKey: [...keys.history, pageSize],
    queryFn: ({ pageParam }) =>
      unwrap(
        api.GET("/v1/me/transactions", {
          params: { query: { limit: pageSize, cursor: pageParam ?? undefined } },
        }),
      ),
    initialPageParam: null as string | null,
    getNextPageParam: (page) => page.next_cursor,
  });
}

/** Newest first. The demo shows codes here instead of sending an SMS. */
export function useInbox(phone: string | null, enabled = true) {
  return useQuery({
    queryKey: keys.inbox(phone ?? ""),
    queryFn: () => unwrap(api.GET("/v1/sandbox/inbox", { params: { query: { phone: phone! } } })),
    enabled: enabled && !!phone,
    refetchInterval: 3_000,
  });
}

export function useRegister() {
  return useMutation({
    mutationFn: (body: { handle: string; phone: string; pin: string }) =>
      unwrap(api.POST("/v1/users", { body })),
  });
}

export function useStartSignIn() {
  return useMutation({
    mutationFn: (body: { phone: string; pin: string }) =>
      unwrap(api.POST("/v1/auth/sign-in", { body })),
  });
}

export function useVerifySignIn() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: { challenge_id: string; code: string }) =>
      unwrap(api.POST("/v1/auth/verify", { body })),
    onSuccess: (me) => {
      resetWallet(queryClient);
      queryClient.setQueryData(keys.me, me);
    },
  });
}

export function useSignOut() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () => unwrap(api.POST("/v1/auth/sign-out")),
    onSettled: () => {
      resetWallet(queryClient);
      queryClient.setQueryData(keys.me, null);
    },
  });
}

export function useStaffMe() {
  return useQuery({
    queryKey: keys.staffMe,
    queryFn: async (): Promise<StaffMe | null> => {
      try {
        return await unwrap(api.GET("/v1/console/me"));
      } catch (error) {
        if (error instanceof ApiError && error.status === 401) return null;
        throw error;
      }
    },
    staleTime: 60_000,
  });
}

export function useStaffSignIn() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: { handle: string; pin: string }) =>
      unwrap(api.POST("/v1/console/sign-in", { body })),
    onSuccess: (staff) => {
      queryClient.setQueryData(keys.staffMe, staff);
    },
  });
}

export function useStaffSignOut() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () => unwrap(api.POST("/v1/console/sign-out")),
    onSettled: () => {
      queryClient.setQueryData(keys.staffMe, null);
      queryClient.removeQueries({ queryKey: ["console-user"] });
      queryClient.removeQueries({ queryKey: ["console-ledger"] });
      queryClient.removeQueries({ queryKey: ["console-journal"] });
      queryClient.removeQueries({ queryKey: keys.consoleRecon });
      queryClient.removeQueries({ queryKey: keys.consoleSuspense });
      queryClient.removeQueries({ queryKey: keys.consoleDlq });
      queryClient.removeQueries({ queryKey: keys.consoleAudit });
    },
  });
}

export function useConsoleUser(handle: string | null) {
  return useQuery({
    queryKey: keys.consoleUser(handle ?? ""),
    enabled: !!handle,
    queryFn: () => unwrap(api.GET("/v1/console/users", { params: { query: { handle: handle! } } })),
  });
}

export function useConsoleUserLedger(userId: string | null) {
  return useQuery({
    queryKey: keys.consoleLedger(userId ?? ""),
    enabled: !!userId,
    queryFn: () =>
      unwrap(
        api.GET("/v1/console/users/{user_id}/ledger", {
          params: { path: { user_id: userId! } },
        }),
      ),
  });
}

export function useConsoleJournal(entryId: string | null) {
  return useQuery({
    queryKey: keys.consoleJournal(entryId ?? ""),
    enabled: !!entryId,
    queryFn: () =>
      unwrap(
        api.GET("/v1/console/journal/{entry_id}", {
          params: { path: { entry_id: entryId! } },
        }),
      ),
  });
}

export function useConsoleRecon() {
  return useQuery({
    queryKey: keys.consoleRecon,
    queryFn: () => unwrap(api.GET("/v1/console/recon/latest")),
  });
}

export function useConsoleSuspense() {
  return useQuery({
    queryKey: keys.consoleSuspense,
    queryFn: () => unwrap(api.GET("/v1/console/suspense")),
  });
}

export function useConsoleDlq() {
  return useQuery({
    queryKey: keys.consoleDlq,
    queryFn: () => unwrap(api.GET("/v1/console/outbox/dlq")),
  });
}

export function useReplayDlq() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (jobId: string) =>
      unwrap(
        api.POST("/v1/console/outbox/{job_id}/replay", {
          params: { path: { job_id: jobId } },
        }),
      ),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: keys.consoleDlq });
      void queryClient.invalidateQueries({ queryKey: keys.consoleAudit });
    },
  });
}

export function useConsoleAudit() {
  return useQuery({
    queryKey: keys.consoleAudit,
    queryFn: () => unwrap(api.GET("/v1/console/audit")),
  });
}

export function useTransferQuote(amountCents: number | null) {
  return useQuery({
    queryKey: ["transfer-quote", amountCents] as const,
    enabled: amountCents !== null && amountCents > 0,
    queryFn: () =>
      unwrap(
        api.GET("/v1/transfers/quote", {
          params: { query: { amount_cents: amountCents! } },
        }),
      ),
  });
}

export function useLookupHandle() {
  return useMutation({
    mutationFn: (handle: string) =>
      unwrap(api.GET("/v1/handles/{handle}", { params: { path: { handle } } })),
  });
}

/** One key per confirmed send, so a retried request can never send twice. */
export function useSend() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({
      idempotencyKey,
      ...body
    }: {
      to: string;
      amount_cents: number;
      note?: string | null;
      idempotencyKey: string;
    }) =>
      unwrap(
        api.POST("/v1/transfers", {
          body,
          params: { header: { "Idempotency-Key": idempotencyKey } },
        }),
      ),
    onSuccess: () => refreshWallet(queryClient),
  });
}

export function useStartTopup() {
  return useMutation({
    mutationFn: ({
      idempotencyKey,
      ...body
    }: {
      amount_cents: number;
      phone?: string | null;
      rail?: Rail;
      idempotencyKey: string;
    }) =>
      unwrap(
        api.POST("/v1/topups", { body, params: { header: { "Idempotency-Key": idempotencyKey } } }),
      ),
  });
}

/** The rails this deployment offers for top-ups, default first. */
export function useRails() {
  return useQuery({
    queryKey: keys.rails,
    queryFn: () => unwrap(api.GET("/v1/payment-rails")),
    staleTime: 5 * 60_000,
  });
}

export function useStartCashout() {
  return useMutation({
    mutationFn: ({
      idempotencyKey,
      ...body
    }: {
      amount_cents: number;
      phone?: string | null;
      rail?: Rail;
      idempotencyKey: string;
    }) =>
      unwrap(
        api.POST("/v1/cashouts", {
          body,
          params: { header: { "Idempotency-Key": idempotencyKey } },
        }),
      ),
  });
}

const FINAL_TOPUP = new Set(["succeeded", "failed", "expired"]);
const FINAL_CASHOUT = new Set(["succeeded", "failed"]);

export function isFinalTopup(topup: Topup | undefined): boolean {
  return !!topup && FINAL_TOPUP.has(topup.status);
}

/** Poll a top-up until M-PESA gives a final answer, then refresh the balance once. */
export function useTopupStatus(id: string | null) {
  const queryClient = useQueryClient();
  return useQuery({
    queryKey: keys.topup(id ?? ""),
    enabled: !!id,
    queryFn: async () => {
      const topup = await unwrap(
        api.GET("/v1/topups/{topup_id}", { params: { path: { topup_id: id! } } }),
      );
      if (isFinalTopup(topup)) refreshWallet(queryClient);
      return topup;
    },
    refetchInterval: (query) => (isFinalTopup(query.state.data) ? false : 1_500),
  });
}

export function isFinalCashout(cashout: Cashout | undefined): boolean {
  return !!cashout && FINAL_CASHOUT.has(cashout.status);
}

/** Poll a cash-out until it succeeds, fails, or expires (then keep showing the expiry). */
export function useCashoutStatus(id: string | null) {
  const queryClient = useQueryClient();
  return useQuery({
    queryKey: keys.cashout(id ?? ""),
    enabled: !!id,
    queryFn: async () => {
      const cashout = await unwrap(
        api.GET("/v1/cashouts/{cashout_id}", { params: { path: { cashout_id: id! } } }),
      );
      if (isFinalCashout(cashout) || cashout.status === "expired") refreshWallet(queryClient);
      return cashout;
    },
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      if (!status || FINAL_CASHOUT.has(status) || status === "expired") return false;
      return 1_500;
    },
  });
}

export { newIdempotencyKey };

function refreshWallet(queryClient: QueryClient) {
  void queryClient.invalidateQueries({ queryKey: keys.balance });
  void queryClient.invalidateQueries({ queryKey: keys.history });
}

function resetWallet(queryClient: QueryClient) {
  queryClient.removeQueries({ queryKey: keys.balance });
  queryClient.removeQueries({ queryKey: keys.history });
}
