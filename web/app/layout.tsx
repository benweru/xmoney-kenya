import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "X Money for Kenya (sandbox)",
  description:
    "Sandbox-only pay-by-@handle wallet prototype. Not affiliated with X Corp. Cannot move real money.",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en" className="h-full antialiased">
      <body className="flex min-h-full flex-col">{children}</body>
    </html>
  );
}
