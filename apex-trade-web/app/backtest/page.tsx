'use client';
import { useEffect, useState } from 'react';
import AppLayout from '@/components/layout/AppLayout';
import { backtestApi } from '@/lib/api';
import { FlaskConical, Play, TrendingUp, TrendingDown, AlertCircle } from 'lucide-react';
import { LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer, ReferenceLine } from 'recharts';
import clsx from 'clsx';

interface Strategy { id: string; name: string; description: string; }
interface BacktestResult { totalReturn: number; sharpeRatio: number; maxDrawdown: number; winRate: number; totalTrades: number; equityCurve: { date: string; value: number }[]; }

const SYMBOLS = ['BTC', 'ETH', 'SOL', 'AAPL', 'NVDA', 'EUR/USD'];
const PERIODS = ['1M', '3M', '6M', '1Y'];

export default function BacktestPage() {
  const [strategies, setStrategies] = useState<Strategy[]>([]);
  const [form, setForm] = useState({ strategy: '', symbol: 'BTC', period: '3M', capital: 1000 });
  const [result, setResult] = useState<BacktestResult | null>(null);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    backtestApi.getStrategies().then((r) => {
      setStrategies(r.data);
      setForm((f) => ({ ...f, strategy: r.data[0]?.id || '' }));
    }).catch(() => {});
  }, []);

  async function runBacktest() {
    if (!form.strategy) return;
    setRunning(true);
    setError('');
    setResult(null);
    try {
      const res = await backtestApi.run(form);
      setResult(res.data);
    } catch (e: any) {
      setError(e.response?.data?.error || 'Eroare la backtest');
    } finally {
      setRunning(false);
    }
  }

  return (
    <AppLayout>
      <div className="p-4 md:p-6 space-y-5 animate-fade-in">
        <h1 className="text-2xl font-bold flex items-center gap-2">
          <FlaskConical className="w-6 h-6 text-primary" /> Backtest Strategii
        </h1>

        {/* Config */}
        <div className="card space-y-4">
          <h2 className="font-semibold">Configurare</h2>
          <div className="grid grid-cols-2 gap-3">
            <div className="col-span-2">
              <label className="text-xs text-muted mb-1 block">Strategie</label>
              <select value={form.strategy} onChange={(e) => setForm({ ...form, strategy: e.target.value })}
                className="w-full bg-surface-2 border border-border rounded-lg px-3 py-2.5 text-sm focus:outline-none focus:border-primary">
                {strategies.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
              </select>
            </div>
            <div>
              <label className="text-xs text-muted mb-1 block">Simbol</label>
              <select value={form.symbol} onChange={(e) => setForm({ ...form, symbol: e.target.value })}
                className="w-full bg-surface-2 border border-border rounded-lg px-3 py-2.5 text-sm focus:outline-none focus:border-primary">
                {SYMBOLS.map((s) => <option key={s}>{s}</option>)}
              </select>
            </div>
            <div>
              <label className="text-xs text-muted mb-1 block">Perioadă</label>
              <select value={form.period} onChange={(e) => setForm({ ...form, period: e.target.value })}
                className="w-full bg-surface-2 border border-border rounded-lg px-3 py-2.5 text-sm focus:outline-none focus:border-primary">
                {PERIODS.map((p) => <option key={p}>{p}</option>)}
              </select>
            </div>
            <div className="col-span-2">
              <label className="text-xs text-muted mb-1 block">Capital inițial ($)</label>
              <input type="number" value={form.capital}
                onChange={(e) => setForm({ ...form, capital: +e.target.value })}
                min={100} step={100}
                className="w-full bg-surface-2 border border-border rounded-lg px-3 py-2.5 text-sm focus:outline-none focus:border-primary" />
            </div>
          </div>
          <button onClick={runBacktest} disabled={running || !form.strategy}
            className="w-full flex items-center justify-center gap-2 bg-primary hover:bg-primary-dark disabled:opacity-50 rounded-lg py-2.5 font-semibold text-sm transition-colors">
            {running ? <><div className="w-4 h-4 border-2 border-white border-t-transparent rounded-full animate-spin" />Rulează...</> : <><Play className="w-4 h-4" />Rulează Backtest</>}
          </button>
        </div>

        {error && (
          <div className="flex items-center gap-2 bg-danger/10 border border-danger/30 text-danger rounded-lg px-3 py-2 text-sm">
            <AlertCircle className="w-4 h-4" />{error}
          </div>
        )}

        {result && (
          <div className="space-y-4 animate-fade-in">
            {/* Metrics */}
            <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
              {[
                { label: 'Return Total', value: `${result.totalReturn >= 0 ? '+' : ''}${result.totalReturn?.toFixed(2)}%`, positive: result.totalReturn >= 0 },
                { label: 'Sharpe Ratio', value: result.sharpeRatio?.toFixed(2), positive: result.sharpeRatio >= 1 },
                { label: 'Max Drawdown', value: `-${result.maxDrawdown?.toFixed(2)}%`, positive: false },
                { label: 'Win Rate', value: `${result.winRate?.toFixed(1)}%`, positive: result.winRate >= 50 },
              ].map(({ label, value, positive }) => (
                <div key={label} className="card text-center">
                  <p className="text-xs text-muted mb-1">{label}</p>
                  <p className={clsx('font-bold num text-lg', positive ? 'text-accent' : 'text-danger')}>{value}</p>
                </div>
              ))}
            </div>

            {/* Equity curve */}
            {result.equityCurve?.length > 0 && (
              <div className="card">
                <p className="font-semibold text-sm mb-3">Curba de Echitate</p>
                <div className="h-48">
                  <ResponsiveContainer width="100%" height="100%">
                    <LineChart data={result.equityCurve}>
                      <XAxis dataKey="date" hide />
                      <YAxis hide domain={['auto', 'auto']} />
                      <Tooltip contentStyle={{ background: '#111', border: '1px solid #222', borderRadius: 8 }}
                        formatter={(v: number) => [`$${v.toLocaleString()}`, 'Valoare']} />
                      <ReferenceLine y={form.capital} stroke="#333" strokeDasharray="3 3" />
                      <Line type="monotone" dataKey="value" stroke="#0066FF" strokeWidth={2} dot={false} />
                    </LineChart>
                  </ResponsiveContainer>
                </div>
              </div>
            )}
          </div>
        )}
      </div>
    </AppLayout>
  );
}
