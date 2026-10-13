const apiUrl = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export default function Home() {
  return (
    <main className="mx-auto flex w-full max-w-xl flex-1 flex-col justify-center gap-8 px-6 py-16">
      <div
        role="note"
        className="rounded-lg border border-amber-500/40 bg-amber-500/10 px-4 py-3 text-sm"
      >
        <strong>Sandbox only.</strong> This prototype cannot move real money. It is not a licensed
        payment service and is not affiliated with X Corp or Safaricom.
      </div>

      <header className="flex flex-col gap-3">
        <h1 className="text-4xl font-semibold tracking-tight">X Money for Kenya</h1>
        <p className="text-lg opacity-80">
          Pay anyone by <span className="font-mono">@handle</span>. Top up from M-PESA, send to{" "}
          <span className="font-mono">@amina</span>, cash out to M-PESA.
        </p>
      </header>

      <section className="flex flex-col gap-2 text-sm opacity-80">
        <p>
          The wallet app is not built yet. This page is the placeholder for the Next.js frontend;
          sign-in, top-up, send, and history arrive in later milestones.
        </p>
        <p>
          The API is running at{" "}
          <a className="underline underline-offset-4" href={`${apiUrl}/docs`}>
            {apiUrl}/docs
          </a>
          .
        </p>
      </section>
    </main>
  );
}
