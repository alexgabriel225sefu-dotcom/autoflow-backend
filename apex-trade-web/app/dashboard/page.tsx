'use client';
import { useEffect, useState } from 'react';
import AppLayout from '@/components/layout/AppLayout';
import { portfolioApi, signalsApi, marketsApi } from '@/lib/api';
import { TrendingUp, TrendingDown, Zap, BarChart2, DollarSign, Target } from 'lucide-react';
import { AreaChart, Area, XAxis, YAxis, Tooltip, ResponsiveContainer } from 'recharts';
import { getUser } from '@/lib/auth';
import Link from 'next/link';

interface Signal {
  id: string;
  symbol: string;
  market: string;
  action: 'BUY' | 'SELL' | 'HOLD';
  confidence: number;
  entryPrice: number;
  targetPrice: number;
  createdAt: string;
}

interface Portfolio {
  totalValue: number;
  totalPnL: number;
  totalPnLPercent: number;
  dailyPnL: number;
  dailyPnLPercent: number;
  winRate: number;
  totalTrades: number;
}

export default function DashboardPage() {
  const user = getUser();
  const [portfolio, setPortfolio] = useState<Portfolio | null>(null);
  const [signals, setSignals] = useState<Signal[]>([]);
  const [pnlData, setPnlData] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    Promise.all([
      portfolioApi.getSummary(),
      signalsApi.getAll(),
      portfolioApi.getPnL('1M'),
    ]).then(([portRes, sigRes, pnlRes]) => {
      setPortfolio(portRes.data);
      setSignals(sigRes.data.slice(0, 3));
      setPnlData(pnlRes.data.slice(-30));
    }).catch(() => {}).finally(() => setLoading(false));
  }, []);

  if (loading) return (
    <AppLayout>
      <div className="flex items-center justify-center h-64">
        <div className="w-8 h-8 border-2 border-primary border-t-transparent rounded-full animate-spin" />
      </div>
    </AppLayout>
  );

  const pnlPositive = (portfolio?.dailyPnL ?? 0) >= 0;

  return (
    <AppLayout>
      <div className="p-4 md:p-6 space-y-6 animate-fade-in">
        {/* Header */}
        <div>
          <p className="text-muted text-sm">Bună ziua,</p>
          <h1 className="text-2xl font-bold">{user?.name?.split(' ')[0] || 'Trader'} 👋</h1>
        </div>

        {/* Stats grid */}
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          <StatCard
            label="Valoare Totală"
            value={`$${portfolio?.totalValue?.toLocaleString('ro', { minimumFractionDigits: 2 }) ?? '0.00'}`}
            icon={<DollarSign className="w-4 h-4" />}
            color="blue"
          />
          <StatCard
            label="Profit Total"
            value={`+$${portfolio?.totalPnL?.toLocaleString('ro', { minimumFractionDigits: 2 }) ?? '0.00'}`}
            sub={`+${portfolio?.totalPnLPercent?.toFixed(2) ?? 0}%`}
            icon={<TrendingUp className="w-4 h-4" />}
            color="green"
          />
          <StatCard
            label="Profit Azi"
            value={`${pnlPositive ? '+' : ''}$${portfolio?.dailyPnL?.toFixed(2) ?? '0.00'}`}
            sub={`${pnlPositive ? '+' : ''}${portfolio?.dailyPnLPercent?.toFixed(2) ?? 0}%`}
            icon={pnlPositive ? <TrendingUp className="w-4 h-4" /> : <TrendingDown className="w-4 h-4" />}
            color={pnlPositive ? 'green' : 'red'}
          />
          <StatCard
            label="Win Rate"
            value={`${portfolio?.winRate ?? 0}%`}
            sub={`${portfolio?.totalTrades ?? 0} tranzacții`}
            icon={<Target className="w-4 h-4" />}
            color="purple"
          />
        </div>

        {/* PnL Chart */}
        <div className="card">
          <div className="flex items-center justify-between mb-4">
            <h2 className="font-semibold">Evoluție Portofoliu</h2>
            <span className="text-xs text-muted">Ultima lună</span>
          </div>
          <div className="h-48">
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart data={pnlData}>
                <defs>
                  <linearGradient id="pnlGrad" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor="#0066FF" stopOpacity={0.3} />
                    <stop offset="95%" stopColor="#0066FF" stopOpacity={0} />
                  </linearGradient>
                </defs>
                <XAxis dataKey="date" hide />
                <YAxis hide domain={['auto', 'auto']} />
                <Tooltip
                  contentStyle={{ background: '#111', border: '1px solid #222', borderRadius: 8 }}
                  labelStyle={{ color: '#666', fontSize: 12 }}
                  formatter={(v: number) => [`$${v.toLocaleString()}`, 'Valoare']}
                />
                <Area type="monotone" dataKey="value" stroke="#0066FF" fill="url(#pnlGrad)" strokeWidth={2} dot={false} />
              </AreaChart>
            </ResponsiveContainer>
          </div>
        </div>

        {/* Recent Signals */}
        <div className="card">
          <div className="flex items-center justify-between mb-4">
            <h2 className="font-semibold flex items-center gap-2">
              <Zap className="w-4 h-4 text-primary" />
              Semnale Recente
            </h2>
            <Link href="/signals" className="text-xs text-primary hover:underline">Vezi toate</Link>
          </div>
          <div className="space-y-3">
            {signals.length === 0 ? (
              <p className="text-muted text-sm text-center py-4">Nu există semnale încă</p>
            ) : signals.map((s) => (
              <div key={s.id} className="flex items-center justify-between py-2 border-b border-border last:border-0">
                <div className="flex items-center gap-3">
                  <div className={`px-2 py-0.5 rounded text-xs font-bold ${
                    s.action === 'BUY' ? 'bg-accent/20 text-accent' : 'bg-danger/20 text-danger'
                  }`}>{s.action}</div>
                  <div>
                    <p className="text-sm font-medium">{s.symbol}</p>
                    <p className="text-xs text-muted capitalize">{s.market}</p>
                  </div>
                </div>
                <div className="text-right">
                  <p className="text-sm font-mono">${s.entryPrice?.toLocaleString()}</p>
                  <p className="text-xs text-primary">{s.confidence}% conf.</p>
                </div>
              </div>
            ))}
          </div>
        </div>

        {/* Quick Actions */}
        <div className="grid grid-cols-2 gap-3">
          <Link href="/signals" className="card hover:border-primary transition-colors flex items-center gap-3">
            <div className="w-10 h-10 bg-primary/20 rounded-xl flex items-center justify-center">
              <Zap className="w-5 h-5 text-primary" />
            </div>
            <div>
              <p className="text-sm font-medium">Semnale AI</p>
              <p className="text-xs text-muted">Generează semnal</p>
            </div>
          </Link>
          <Link href="/backtest" className="card hover:border-primary transition-colors flex items-center gap-3">
            <div className="w-10 h-10 bg-accent/10 rounded-xl flex items-center justify-center">
              <BarChart2 className="w-5 h-5 text-accent" />
            </div>
            <div>
              <p className="text-sm font-medium">Backtest</p>
              <p className="text-xs text-muted">Testează strategie</p>
            </div>
          </Link>
        </div>
      </div>
    </AppLayout>
  );
}

function StatCard({ label, value, sub, icon, color }: any) {
  const colors: Record<string, string> = {
    blue: 'bg-primary/10 text-primary',
    green: 'bg-accent/10 text-accent',
    red: 'bg-danger/10 text-danger',
    purple: 'bg-purple-500/10 text-purple-400',
  };
  return (
    <div className="card">
      <div className={`w-8 h-8 rounded-lg flex items-center justify-center mb-2 ${colors[color]}`}>
        {icon}
      </div>
      <p className="text-xs text-muted mb-1">{label}</p>
      <p className="font-bold num text-sm">{value}</p>
      {sub && <p className="text-xs text-muted num mt-0.5">{sub}</p>}
    </div>
  );
}
