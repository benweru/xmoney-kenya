export function SandboxBanner() {
  return (
    <div
      role="note"
      aria-label="Sandbox disclaimer"
      className="bg-warn-soft px-4 py-2 text-center text-xs leading-snug font-medium text-warn"
    >
      <strong className="font-semibold">Sandbox demo.</strong> No real money moves. Not affiliated
      with X Corp or Safaricom.
    </div>
  );
}

export function Disclaimer() {
  return (
    <p className="px-2 text-center text-xs leading-relaxed text-muted">
      X Money for Kenya is an independent portfolio project. It is not built, endorsed, or sponsored
      by X Corp. or Safaricom, is not a Central Bank of Kenya licensed payment service, and cannot
      move real money. M-PESA prompts go to Safaricom&apos;s Daraja sandbox or a local mock.
    </p>
  );
}
