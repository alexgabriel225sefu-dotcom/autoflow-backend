import type { Metadata } from "next";
import { Geist, Geist_Mono, Familjen_Grotesk } from "next/font/google";
import "./globals.css";
import { NO_FLASH_SCRIPT } from "@/lib/appearance";
import { SITE_URL } from "@/lib/site";
import { RippleListener } from "@/components/ui/ripple-listener";
import { PressGlowListener } from "@/components/ui/press-glow-listener";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

// The marketing page's own face. The app keeps Geist; the landing page is the
// one place a visitor judges the product by its look, and Geist at heavy
// weights with tight tracking is the default of every template.
const mktSans = Familjen_Grotesk({
  variable: "--font-mkt",
  subsets: ["latin"],
  weight: ["400", "500", "600", "700"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  // The root layout titles every page, including the platform's own screens.
  // It previously carried the old product's name and described crypto source
  // code, so a client on /dashboard read "Apex Trade Bot" in their browser tab.
  // A plain default, with no template: a template would append "· Apex4Traders"
  // to pages that still carry the previous product's name, which would read
  // worse than leaving them alone until that copy is decided on.
  title: "Your trading rule, tested on demo first",
  description:
    "Write your own rule, connect your cTrader account, and test it on a free " +
    "14-day demo before you automate anything.",
  // One public origin for search engines. Without it the same page is
  // reachable at the onrender.com address too, and the two compete.
  metadataBase: new URL(SITE_URL),
  alternates: { canonical: "/" },
  applicationName: "Apex4Traders",
  // The preview image is what a phone shows in Instagram, WhatsApp and the
  // browser share sheet. Without it the platform crops the small site icon,
  // which is why the logo read as "EX4".
  openGraph: {
    type: "website",
    url: SITE_URL,
    siteName: "Apex4Traders",
    title: "Your trading rule, tested on demo first",
    description:
      "Write your own rule, connect your cTrader account, and test it on a free " +
      "14-day demo before you automate anything.",
    images: [{ url: "/og-image.png", width: 1200, height: 630, alt: "Apex4Traders" }],
  },
  twitter: {
    card: "summary_large_image",
    title: "Your trading rule, tested on demo first",
    description:
      "Write your own rule, connect your cTrader account, and test it on a free " +
      "14-day demo before you automate anything.",
    images: ["/og-image.png"],
  },
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html
      lang="en"
      className={`${geistSans.variable} ${geistMono.variable} ${mktSans.variable} h-full antialiased`}
      // The theme attributes are written by the script below before first
      // paint, so the server's markup and the browser's differ on purpose.
      suppressHydrationWarning
    >
      <head>
        <script dangerouslySetInnerHTML={{ __html: NO_FLASH_SCRIPT }} />
      </head>
      <body className="min-h-full flex flex-col">
        {children}
        <RippleListener />
        <PressGlowListener />
      </body>
    </html>
  );
}
