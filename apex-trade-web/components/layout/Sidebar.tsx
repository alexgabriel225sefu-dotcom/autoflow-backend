'use client';
import Link from 'next/link';
import { usePathname, useRouter } from 'next/navigation';
import { TrendingUp, LayoutDashboard, BarChart2, Zap, FlaskConical, Briefcase, Settings, LogOut } from 'lucide-react';
import { clearAuth, getUser } from '@/lib/auth';
import clsx from 'clsx';

const nav = [
  { href: '/dashboard', icon: LayoutDashboard, label: 'Dashboard' },
  { href: '/markets', icon: BarChart2, label: 'Piețe' },
  { href: '/signals', icon: Zap, label: 'Semnale AI' },
  { href: '/backtest', icon: FlaskConical, label: 'Backtest' },
  { href: '/portfolio', icon: Briefcase, label: 'Portofoliu' },
  { href: '/settings', icon: Settings, label: 'Setări' },
];

export default function Sidebar() {
  const pathname = usePathname();
  const router = useRouter();
  const user = getUser();

  function handleLogout() {
    clearAuth();
    router.push('/login');
  }

  return (
    <aside className="hidden md:flex flex-col w-60 bg-surface border-r border-border h-screen fixed left-0 top-0 z-40">
      {/* Logo */}
      <div className="flex items-center gap-3 px-5 py-5 border-b border-border">
        <div className="w-9 h-9 bg-primary rounded-xl flex items-center justify-center flex-shrink-0">
          <TrendingUp className="w-5 h-5 text-white" />
        </div>
        <div>
          <p className="font-bold text-sm leading-none">Apex Trade</p>
          <p className="text-xs text-muted mt-0.5">AI Platform</p>
        </div>
      </div>

      {/* Nav */}
      <nav className="flex-1 px-3 py-4 space-y-1">
        {nav.map(({ href, icon: Icon, label }) => {
          const active = pathname === href;
          return (
            <Link key={href} href={href}
              className={clsx(
                'flex items-center gap-3 px-3 py-2.5 rounded-xl text-sm font-medium transition-all',
                active
                  ? 'bg-primary text-white'
                  : 'text-muted hover:text-white hover:bg-surface-2'
              )}>
              <Icon className="w-4 h-4 flex-shrink-0" />
              {label}
            </Link>
          );
        })}
      </nav>

      {/* User */}
      <div className="px-3 py-4 border-t border-border">
        <div className="flex items-center gap-3 px-3 py-2 mb-1">
          <div className="w-8 h-8 bg-primary/20 rounded-full flex items-center justify-center text-primary font-bold text-sm">
            {user?.name?.[0]?.toUpperCase() || 'U'}
          </div>
          <div className="flex-1 min-w-0">
            <p className="text-sm font-medium truncate">{user?.name || 'User'}</p>
            <p className="text-xs text-muted capitalize">{user?.plan || 'free'}</p>
          </div>
        </div>
        <button onClick={handleLogout}
          className="flex items-center gap-3 px-3 py-2 w-full text-muted hover:text-danger hover:bg-danger/10 rounded-xl text-sm transition-all">
          <LogOut className="w-4 h-4" />
          Deconectare
        </button>
      </div>
    </aside>
  );
}
