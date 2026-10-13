import Link from "next/link";
import type { ComponentProps, ReactNode } from "react";

function cx(...classes: (string | false | null | undefined)[]): string {
  return classes.filter(Boolean).join(" ");
}

const buttonBase =
  "inline-flex h-12 w-full items-center justify-center gap-2 rounded-2xl px-5 text-base font-semibold transition focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brand disabled:cursor-not-allowed disabled:opacity-50";

const buttonVariants = {
  primary: "bg-brand text-white shadow-sm hover:bg-brand-strong active:scale-[0.99]",
  secondary: "border border-line bg-white text-ink hover:bg-surface",
  ghost: "text-brand hover:bg-brand-soft",
} as const;

type Variant = keyof typeof buttonVariants;

export function Button({
  variant = "primary",
  loading = false,
  className,
  children,
  disabled,
  ...props
}: ComponentProps<"button"> & { variant?: Variant; loading?: boolean }) {
  return (
    <button
      className={cx(buttonBase, buttonVariants[variant], className)}
      disabled={disabled || loading}
      aria-busy={loading || undefined}
      {...props}
    >
      {loading && <Spinner className="size-4" />}
      {children}
    </button>
  );
}

export function ButtonLink({
  variant = "primary",
  className,
  ...props
}: ComponentProps<typeof Link> & { variant?: Variant }) {
  return <Link className={cx(buttonBase, buttonVariants[variant], className)} {...props} />;
}

export function Field({
  label,
  hint,
  error,
  children,
  htmlFor,
}: {
  label: string;
  hint?: ReactNode;
  error?: string | null;
  children: ReactNode;
  htmlFor: string;
}) {
  return (
    <div className="flex flex-col gap-1.5">
      <label htmlFor={htmlFor} className="text-sm font-medium text-ink">
        {label}
      </label>
      {children}
      {error ? (
        <p className="text-sm text-danger" id={`${htmlFor}-error`}>
          {error}
        </p>
      ) : hint ? (
        <p className="text-sm text-muted">{hint}</p>
      ) : null}
    </div>
  );
}

export function Input({
  className,
  prefix,
  ...props
}: ComponentProps<"input"> & { prefix?: string }) {
  const input = (
    <input
      className={cx(
        "h-12 w-full rounded-2xl border border-line bg-white px-4 text-base text-ink placeholder:text-muted/70 focus:border-brand focus:ring-2 focus:ring-brand/20 focus:outline-none aria-invalid:border-danger",
        prefix && "pl-14",
        className,
      )}
      {...props}
    />
  );
  if (!prefix) return input;
  return (
    <div className="relative">
      <span className="pointer-events-none absolute inset-y-0 left-4 flex items-center text-base font-medium text-muted">
        {prefix}
      </span>
      {input}
    </div>
  );
}

export function Card({ className, ...props }: ComponentProps<"div">) {
  return (
    <div
      className={cx(
        "rounded-3xl border border-line bg-white p-5 shadow-[0_1px_2px_rgb(0_0_0/0.04)]",
        className,
      )}
      {...props}
    />
  );
}

export function Spinner({ className }: { className?: string }) {
  return (
    <svg className={cx("animate-spin", className)} viewBox="0 0 24 24" fill="none" aria-hidden>
      <circle cx="12" cy="12" r="10" stroke="currentColor" strokeOpacity="0.25" strokeWidth="4" />
      <path
        d="M22 12a10 10 0 0 0-10-10"
        stroke="currentColor"
        strokeWidth="4"
        strokeLinecap="round"
      />
    </svg>
  );
}

export function Alert({
  tone = "danger",
  title,
  children,
  action,
}: {
  tone?: "danger" | "warn" | "success" | "info";
  title?: string;
  children?: ReactNode;
  action?: ReactNode;
}) {
  const tones = {
    danger: "border-danger/20 bg-danger-soft text-danger",
    warn: "border-warn/20 bg-warn-soft text-warn",
    success: "border-brand/20 bg-brand-soft text-brand-strong",
    info: "border-line bg-white text-ink",
  } as const;
  return (
    <div
      role={tone === "danger" ? "alert" : "status"}
      className={cx("rounded-2xl border px-4 py-3 text-sm", tones[tone])}
    >
      {title && <p className="font-semibold">{title}</p>}
      {children && <div className={cx(title && "mt-0.5", "opacity-90")}>{children}</div>}
      {action && <div className="mt-2">{action}</div>}
    </div>
  );
}

export function Skeleton({ className }: { className?: string }) {
  return <div className={cx("skeleton rounded-xl", className)} aria-hidden />;
}

export function EmptyState({
  icon,
  title,
  children,
  action,
}: {
  icon: ReactNode;
  title: string;
  children?: ReactNode;
  action?: ReactNode;
}) {
  return (
    <div className="flex flex-col items-center gap-3 px-6 py-10 text-center">
      <div className="flex size-14 items-center justify-center rounded-full bg-brand-soft text-brand">
        {icon}
      </div>
      <p className="text-base font-semibold">{title}</p>
      {children && <p className="max-w-xs text-sm text-muted">{children}</p>}
      {action && <div className="mt-1 w-full max-w-xs">{action}</div>}
    </div>
  );
}

export function PageTitle({ title, subtitle }: { title: string; subtitle?: ReactNode }) {
  return (
    <div className="flex flex-col gap-1">
      <h1 className="text-2xl font-bold tracking-tight">{title}</h1>
      {subtitle && <p className="text-sm text-muted">{subtitle}</p>}
    </div>
  );
}

export { cx };
