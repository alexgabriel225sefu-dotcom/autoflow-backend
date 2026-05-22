import type { Metadata, Viewport } from 'next';
import './globals.css';

export const metadata: Metadata = {
  title: 'Apex Trade — AI Trading Platform',
  description: 'Platformă de trading cu AI pentru crypto, acțiuni și forex',
  manifest: '/manifest.json',
  icons: { icon: '/favicon.ico' },
  openGraph: {
    title: 'Apex Trade',
    description: 'AI Trading Signals & Auto-Trading Platform',
    type: 'website',
  },
};

export const viewport: Viewport = {
  themeColor: '#000000',
  width: 'device-width',
  initialScale: 1,
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="ro">
      <body className="bg-background text-white antialiased">{children}</body>
    </html>
  );
}
