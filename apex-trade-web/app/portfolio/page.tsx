'use client';
import { useEffect, useState } from 'react';
import AppLayout from '@/components/layout/AppLayout';
import { portfolioApi } from '@/lib/api';
import { TrendingUp, TrendingDown, Briefcase } from 'lucide-react';
import { AreaChart, Area, XAxis, YAxis, Tooltip, ResponsiveContainer } from 'recharts';
import clsx from 'clsx';

const PERIODS = ['1D', '1W', '1M', '3M', '1Y'];

export default function PortfolioPage() {
  const [summary, setSummary] = useState<any>(null);
  const [positions, setPositions] = useState<any[]>([]);
  const [pnl, setPnl] = useState<any[]>([]);
  const [period, setPeriod] = useState('1M');
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    Promise.all([
      portfolioApi.getSummary(),
      portfolioApi.getPositions(),
      portfolioApi.getPnL(period),
    ]).then(([s, p, pnlR]) => {
      setSummary(s.data);
      setPositions(p.data);
      setPnl(pnlR.data);
    }).catch(() => {}).finally(() => setLoading(false));
  }, [period]);

  if (loading) return <AppLayout><div className="flex justify-center py-20"><div className="w-8 h-8 border-2 border-primary border-t-transparent rounded-full animate-spin" /></div></AppLayout>;

  return (
    <AppLayout>
      <div className="p-4 md:p-6 space-y-5 animate-fade-in">
        <h1 className="text-2xl font-bold flex items-center gap-2">
          <Briefcase className="w-6 h-6 text-primary" /> Portofoliu
        </h1>

        {/* Summary */}
        <div className="card text-center py-6">
          <p className="text-muted text-sm mb-1">Valoare Totală</p>
          <p className="text-4xl font-bold num">${summary?.totalValue?.toLocaleString('en', { minimumFractionDigits: 2 })}</p>
          <div className={clsx('flex items-center justify-center gap-1 mt-2 text-sm num',
            summary?.dailyPnL >= 0 ? 'text-accent' : 'text-danger')}>
            {summary?.dailyPnL >= 0 ? <TrendingUp className="w-4 h-4" /> : <TrendingDown className="w-4 h-4" />}
            {summary?.dailyPnL >= 0 ? '+' : ''}${summary?.dailyPnL?.toFixed(2)} azi ({summary?.dailyPnLPercent?.toFixed(2)}%)
          </div>
          <div className="grid grid-cols-3 gap-4 mt-4 pt-4 border-t border-border">
            <div><p className="text-xs text-muted">Profit Total</p><p className="font-bold text-accent num">+${summary?.totalPnL?.toFixed(0)}</p></div>
            <div><p className="text-xs text-muted">Win Rate</p><p className="font-bold num">{summary?.winRate}%</p></div>
            <div><p className="text-xs text-muted">Tranzacții</p><p className="font-bold num">{summary?.totalTrades}</p></div>
          </div>
        </div>

        {/* Chart */}
        <div className="card">
          <div className="flex items-center justify-between mb-3">
            <p className="font-semibold text-sm">Evoluție</p>
            <div className="flex gap-1">
              {PERIODS.map((p) => (
                <button key={p} onClick={() => setPeriod(p)}
                  className={clsx('px-2 py-0.5 rounded text-xs font-medium transition-all',
                    period === p ? 'bg-primary text-white' : 'text-muted hover:text-white')}>
                  {p}
                </button>
              ))}
            </div>
          </div>
          <div className="h-40">
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart data={pnl}>
                <defs>
                  <linearGradient id="grad" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor="#00FF88" stopOpacity={0.3} />
                    <stop offset="95%" stopColor="#00FF88" stopOpacity={0} />
                  </linearGradient>
                </defs>
                <XAxis dataKey="date" hide />
                <YAxis hide domain={['auto', 'auto']} />
                <Tooltip contentStyle={{ background: '#111', border: '1px solid #222', borderRadius: 8 }}
                  formatter={(v: number) => [`$${v.toLocaleString()}`, 'Valoare']} />
                <Area type="monotone" dataKey="value" stroke="#00FF88" fill="url(#grad)" strokeWidth={2} dot={false} />
              </AreaChart>
            </ResponsiveContainer>
          </div>
        </div>

        {/* Positions */}
        <div className="card">
          <h2 className="font-semibold mb-3">Poziții Deschise</h2>
          {positions.length === 0 ? (
            <p className="text-muted text-sm text-center py-6">Nicio poziție deschisă</p>
          ) : (
            <div className="space-y-3">
              {positions.map((pos) => (
                <div key={pos.id} className="flex items-center justify-between py-2 border-b border-border last:border-0">
                  <div>
                    <div className="flex items-center gap-2">
                      <p className="font-medium text-sm">{pos.symbol}</p>
                      <span className={clsx('text-xs px-1.5 py-0.5 rounded capitalize',
                        pos.side === 'long' ? 'bg-accent/10 text-accent' : 'bg-danger/10 text-danger')}>
                        {pos.side}
                      </span>
                    </div>
                    <p className="text-xs text-muted">{pos.quantity} unități @ ${pos.entryPrice?.toLocaleString()}</p>
                  </div>
                  <div className="text-right">
                    <p className={clsx('font-medium num text-sm', pos.pnl >= 0 ? 'text-accent' : 'text-danger')}>
                      {pos.pnl >= 0 ? '+' : ''}${pos.pnl?.toFixed(2)}
                    </p>
                    <p className="text-xs text-muted">{pos.pnlPercent >= 0 ? '+' : ''}{pos.pnlPercent?.toFixed(2)}%</p>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </AppLayout>
  );
}
