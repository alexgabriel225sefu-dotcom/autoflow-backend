'use client';
import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { LayoutDashboard, BarChart2, Zap, FlaskConical, Briefcase } from 'lucide-react';
import clsx from 'clsx';

const nav = [
  { href: '/dashboard', icon: LayoutDashboard, label: 'Home' },
  { href: '/markets', icon: BarChart2, label: 'Piețe' },
  { href: '/signals', icon: Zap, label: 'Semnale' },
  { href: '/backtest', icon: FlaskConical, label: 'Backtest' },
  { href: '/portfolio', icon: Briefcase, label: 'Portofoliu' },
];

export default function BottomNav() {
  const pathname = usePathname();
  return (
    <nav className="md:hidden fixed bottom-0 left-0 right-0 bg-surface border-t border-border z-40 px-2 pb-safe">
      <div className="flex items-center justify-around py-2">
        {nav.map(({ href, icon: Icon, label }) => {
          const active = pathname === href;
          return (
            <Link key={href} href={href}
              className={clsx('flex flex-col items-center gap-1 px-3 py-1.5 rounded-xl transition-all',
                active ? 'text-primary' : 'text-muted hover:text-white')}>
              <Icon className="w-5 h-5" />
              <span className="text-[10px] font-medium">{label}</span>
            </Link>
          );
        })}
      </div>
    </nav>
  );
}
