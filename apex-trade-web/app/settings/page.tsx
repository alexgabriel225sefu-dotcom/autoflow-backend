'use client';
import { useState } from 'react';
import AppLayout from '@/components/layout/AppLayout';
import { getUser, clearAuth } from '@/lib/auth';
import { useRouter } from 'next/navigation';
import { Settings, User, Bell, Shield, LogOut, ChevronRight, ExternalLink } from 'lucide-react';

export default function SettingsPage() {
  const user = getUser();
  const router = useRouter();
  const [notifications, setNotifications] = useState(true);

  function handleLogout() {
    clearAuth();
    router.push('/login');
  }

  return (
    <AppLayout>
      <div className="p-4 md:p-6 space-y-5 animate-fade-in">
        <h1 className="text-2xl font-bold flex items-center gap-2">
          <Settings className="w-6 h-6 text-primary" /> Setări
        </h1>

        {/* Profile */}
        <div className="card">
          <h2 className="text-xs text-muted font-medium uppercase mb-3">Profil</h2>
          <div className="flex items-center gap-4 mb-4">
            <div className="w-16 h-16 bg-primary/20 rounded-full flex items-center justify-center text-primary font-bold text-2xl">
              {user?.name?.[0]?.toUpperCase() || 'U'}
            </div>
            <div>
              <p className="font-semibold">{user?.name}</p>
              <p className="text-sm text-muted">{user?.email}</p>
              <span className="inline-block mt-1 px-2 py-0.5 bg-primary/20 text-primary text-xs rounded-full capitalize">{user?.plan} Plan</span>
            </div>
          </div>
        </div>

        {/* Preferences */}
        <div className="card">
          <h2 className="text-xs text-muted font-medium uppercase mb-3">Preferințe</h2>
          <div className="flex items-center justify-between py-2">
            <div className="flex items-center gap-3">
              <Bell className="w-4 h-4 text-muted" />
              <span className="text-sm">Notificări semnale</span>
            </div>
            <button onClick={() => setNotifications(!notifications)}
              className={`relative w-11 h-6 rounded-full transition-colors ${notifications ? 'bg-primary' : 'bg-border'}`}>
              <span className={`absolute top-0.5 left-0.5 w-5 h-5 bg-white rounded-full shadow transition-transform ${notifications ? 'translate-x-5' : ''}`} />
            </button>
          </div>
        </div>

        {/* Plan */}
        <div className="card border-primary/30 bg-primary/5">
          <h2 className="text-xs text-muted font-medium uppercase mb-3">Abonament</h2>
          <div className="flex items-center justify-between">
            <div>
              <p className="font-semibold capitalize">{user?.plan} Plan</p>
              <p className="text-sm text-muted">{user?.plan === 'free' ? 'Upgrade pentru funcții avansate' : 'Plan activ'}</p>
            </div>
            {user?.plan === 'free' && (
              <button className="bg-primary hover:bg-primary-dark rounded-lg px-4 py-2 text-sm font-medium transition-colors">
                Upgrade
              </button>
            )}
          </div>
        </div>

        {/* Info */}
        <div className="card">
          <h2 className="text-xs text-muted font-medium uppercase mb-3">Informații</h2>
          <div className="space-y-1 text-sm text-muted">
            <p>Apex Trade v1.0.0</p>
            <p>© 2026 Apex Trade. Toate drepturile rezervate.</p>
            <p className="text-xs mt-2">⚠️ Tranzacționarea implică riscuri. Performanțele trecute nu garantează rezultate viitoare.</p>
          </div>
        </div>

        {/* Logout */}
        <button onClick={handleLogout}
          className="w-full flex items-center justify-center gap-2 border border-danger/30 hover:bg-danger/10 text-danger rounded-xl py-3 text-sm font-medium transition-all">
          <LogOut className="w-4 h-4" />
          Deconectare
        </button>
      </div>
    </AppLayout>
  );
}
