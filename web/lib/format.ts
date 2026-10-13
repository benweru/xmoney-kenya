const shillings = new Intl.NumberFormat("en-KE", {
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});

/** 123456 cents → "KES 1,234.56". Intl's en-KE currency style says "Ksh"; the API says KES. */
export function formatKes(cents: number): string {
  const sign = cents < 0 ? "−" : "";
  return `${sign}KES ${shillings.format(Math.abs(cents) / 100)}`;
}

/** A signed amount for history rows: "+ KES 500.00" or "− KES 250.00". */
export function formatSignedKes(cents: number): string {
  const sign = cents > 0 ? "+" : cents < 0 ? "−" : "";
  return `${sign} ${formatKes(Math.abs(cents))}`.trim();
}

/** "500" or "1,250.50" shillings → cents, or null if it is not a positive amount. */
export function parseKesToCents(input: string): number | null {
  const cleaned = input.replace(/[,\s]/g, "").replace(/^KES/i, "");
  if (!/^\d+(\.\d{1,2})?$/.test(cleaned)) return null;
  const [whole, fraction = ""] = cleaned.split(".");
  const cents = Number(whole) * 100 + Number(fraction.padEnd(2, "0"));
  return Number.isSafeInteger(cents) && cents > 0 ? cents : null;
}

/** Accept 0712 345 678, 712345678, 254712345678, or +254712345678; return E.164 or null. */
export function normalizeKenyanPhone(input: string): string | null {
  const digits = input.replace(/[\s-]/g, "");
  const match = /^(?:\+?254|0)?([17]\d{8})$/.exec(digits);
  return match ? `+254${match[1]}` : null;
}

/** "+254712345678" → "+254 712 345 678". */
export function formatPhone(e164: string): string {
  const match = /^\+254(\d{3})(\d{3})(\d{3})$/.exec(e164);
  return match ? `+254 ${match[1]} ${match[2]} ${match[3]}` : e164;
}

export function normalizeHandle(input: string): string {
  return input.trim().replace(/^@/, "").toLowerCase();
}

const dateTime = new Intl.DateTimeFormat("en-KE", {
  day: "numeric",
  month: "short",
  hour: "2-digit",
  minute: "2-digit",
});

export function formatWhen(iso: string): string {
  return dateTime.format(new Date(iso));
}
