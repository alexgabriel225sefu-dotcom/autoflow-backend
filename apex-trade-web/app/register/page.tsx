'use client';
import { useState } from 'react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { authApi } from '@/lib/api';
import { setAuth } from '@/lib/auth';
import { TrendingUp, Eye, EyeOff, AlertCircle, CheckCircle } from 'lucide-react';

export default function RegisterPage() {
  const router = useRouter();
  const [form, setForm] = useState({ name: '', email: '', password: '' });
  const [showPass, setShowPass] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  const passwordStrength = form.password.length >= 8
    ? form.password.length >= 12 ? 'strong' : 'medium'
    : form.password.length > 0 ? 'weak' : '';

  async function handleRegister(e: React.FormEvent) {
    e.preventDefault();
    setError('');
    if (form.password.length < 8) {
      setError('Parola trebuie să aibă minim 8 caractere');
      return;
    }
    setLoading(true);
    try {
      const res = await authApi.register(form.email, form.password, form.name);
      setAuth(res.data.token, res.data.user);
      router.push('/dashboard');
    } catch (err: any) {
      setError(err.response?.data?.error || 'Eroare la înregistrare');
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="min-h-screen flex flex-col items-center justify-center px-4 bg-background">
      <div className="mb-8 text-center animate-fade-in">
        <div className="w-16 h-16 bg-primary rounded-2xl flex items-center justify-center mx-auto mb-3 animate-pulse-glow">
          <TrendingUp className="w-9 h-9 text-white" />
        </div>
        <h1 className="text-2xl font-bold">Apex Trade</h1>
        <p className="text-muted text-sm mt-1">Creează cont gratuit</p>
      </div>

      <div className="w-full max-w-sm bg-surface border border-border rounded-2xl p-6 animate-slide-up">
        <h2 className="text-xl font-semibold mb-6">Înregistrare</h2>

        {error && (
          <div className="flex items-center gap-2 bg-danger/10 border border-danger/30 text-danger rounded-lg px-3 py-2 mb-4 text-sm">
            <AlertCircle className="w-4 h-4 flex-shrink-0" />
            {error}
          </div>
        )}

        <form onSubmit={handleRegister} className="space-y-4">
          <div>
            <label className="text-xs text-muted mb-1 block">Nume complet</label>
            <input
              type="text"
              value={form.name}
              onChange={(e) => setForm({ ...form, name: e.target.value })}
              placeholder="Ion Popescu"
              required
              className="w-full bg-surface-2 border border-border rounded-lg px-3 py-2.5 text-sm focus:outline-none focus:border-primary transition-colors placeholder:text-muted"
            />
          </div>

          <div>
            <label className="text-xs text-muted mb-1 block">Email</label>
            <input
              type="email"
              value={form.email}
              onChange={(e) => setForm({ ...form, email: e.target.value })}
              placeholder="email@exemplu.com"
              required
              className="w-full bg-surface-2 border border-border rounded-lg px-3 py-2.5 text-sm focus:outline-none focus:border-primary transition-colors placeholder:text-muted"
            />
          </div>

          <div>
            <label className="text-xs text-muted mb-1 block">Parolă</label>
            <div className="relative">
              <input
                type={showPass ? 'text' : 'password'}
                value={form.password}
                onChange={(e) => setForm({ ...form, password: e.target.value })}
                placeholder="Minim 8 caractere"
                required
                className="w-full bg-surface-2 border border-border rounded-lg px-3 py-2.5 pr-10 text-sm focus:outline-none focus:border-primary transition-colors placeholder:text-muted"
              />
              <button type="button" onClick={() => setShowPass(!showPass)}
                className="absolute right-3 top-1/2 -translate-y-1/2 text-muted hover:text-white transition-colors">
                {showPass ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
              </button>
            </div>
            {passwordStrength && (
              <div className="flex gap-1 mt-1.5">
                {['weak', 'medium', 'strong'].map((level, i) => (
                  <div key={i} className={`h-1 flex-1 rounded-full transition-colors ${
                    (passwordStrength === 'weak' && i === 0) ? 'bg-danger' :
                    (passwordStrength === 'medium' && i <= 1) ? 'bg-warning' :
                    (passwordStrength === 'strong') ? 'bg-accent' : 'bg-border'
                  }`} />
                ))}
              </div>
            )}
          </div>

          <button type="submit" disabled={loading}
            className="w-full bg-primary hover:bg-primary-dark disabled:opacity-50 disabled:cursor-not-allowed rounded-lg py-2.5 font-semibold text-sm transition-colors">
            {loading ? (
              <span className="flex items-center justify-center gap-2">
                <div className="w-4 h-4 border-2 border-white border-t-transparent rounded-full animate-spin" />
                Se creează contul...
              </span>
            ) : 'Creează cont gratuit'}
          </button>
        </form>

        <p className="text-center text-sm text-muted mt-4">
          Ai deja cont?{' '}
          <Link href="/login" className="text-primary hover:underline">Autentifică-te</Link>
        </p>
      </div>
    </div>
  );
}
