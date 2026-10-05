import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import "./globals.css";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
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
  title: "Apex4Traders — rule-based trading automation",
  description:
    "Build trading rules from named, testable conditions, preview what they " +
    "would decide, and run them on a cTrader account you connect yourself.",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html
      lang="en"
      className={`${geistSans.variable} ${geistMono.variable} h-full antialiased`}
    >
      <body className="min-h-full flex flex-col">{children}</body>
    </html>
  );
}
