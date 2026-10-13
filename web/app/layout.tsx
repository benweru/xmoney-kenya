import type { Metadata, Viewport } from "next";

import { Providers } from "@/components/providers";
import { SandboxBanner } from "@/components/sandbox-banner";

import "./globals.css";

export const metadata: Metadata = {
  title: { default: "X Money Kenya (sandbox)", template: "%s · X Money Kenya (sandbox)" },
  description:
    "Sandbox-only pay-by-@handle wallet prototype. Not affiliated with X Corp or Safaricom. Cannot move real money.",
  applicationName: "X Money Kenya",
  manifest: "/manifest.webmanifest",
  icons: { apple: "/apple-touch-icon.png" },
  appleWebApp: { capable: true, title: "X Money", statusBarStyle: "default" },
  robots: { index: false, follow: false },
};

export const viewport: Viewport = {
  themeColor: "#0b1215",
  width: "device-width",
  initialScale: 1,
  viewportFit: "cover",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en-KE" className="h-full antialiased">
      <body className="flex min-h-full flex-col">
        <SandboxBanner />
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
