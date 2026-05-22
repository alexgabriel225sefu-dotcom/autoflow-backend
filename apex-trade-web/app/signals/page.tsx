'use client';
import { useEffect, useState } from 'react';
import AppLayout from '@/components/layout/AppLayout';
import { signalsApi } from '@/lib/api';
import { Zap, RefreshCw, TrendingUp, TrendingDown, AlertCircle, Loader2 } from 'lucide-react';
import clsx from 'clsx';

interface Signal {
  id: string; symbol: string; market: string;
  action: 'BUY' | 'SELL' | 'HOLD';
  confidence: number; entryPrice: number; targetPrice: number;
  stopLoss: number; riskRewardRatio: number; timeframe: string;
  reasoning: string; createdAt: string;
}

const WATCHLIST = [
  { symbol: 'BTC', market: 'crypto' }, { symbol: 'ETH', market: 'crypto' },
  { symbol: 'SOL', market: 'crypto' }, { symbol: 'AAPL', market: 'stocks' },
  { symbol: 'NVDA', market: 'stocks' }, { symbol: 'EUR/USD', market: 'forex' },
];

export default function SignalsPage() {
  const [signals, setSignals] = useState<Signal[]>([]);
  const [loading, setLoading] = useState(true);
  const [analyzing, setAnalyzing] = useState<string | null>(null);
  const [selected, setSelected] = useState<Signal | null>(null);
  const [marketFilter, setMarketFilter] = useState('all');

  useEffect(() => {
    signalsApi.getAll().then((r) => setSignals(r.data)).catch(() => {}).finally(() => setLoading(false));
  }, []);

  async function analyzeSymbol(symbol: string, market: string) {
    setAnalyzing(`${symbol}_${market}`);
    try {
      const res = await signalsApi.analyze(symbol, market);
      setSignals((prev) => [res.data, ...prev.slice(0, 49)]);
      setSelected(res.data);
    } catch {} finally {
      setAnalyzing(null);
    }
  }

  const filtered = marketFilter === 'all' ? signals : signals.filter((s) => s.market === marketFilter);

  return (
    <AppLayout>
      <div className="p-4 md:p-6 space-y-4 animate-fade-in">
        <div className="flex items-center justify-between">
          <h1 className="text-2xl font-bold flex items-center gap-2">
            <Zap className="w-6 h-6 text-primary" /> Semnale AI
          </h1>
        </div>

        {/* Analyze buttons */}
        <div>
          <p className="text-xs text-muted mb-2">Analizează rapid:</p>
          <div className="flex flex-wrap gap-2">
            {WATCHLIST.map(({ symbol, market }) => (
              <button key={`${symbol}_${market}`}
                onClick={() => analyzeSymbol(symbol, market)}
                disabled={!!analyzing}
                className="flex items-center gap-1.5 px-3 py-1.5 bg-surface border border-border hover:border-primary rounded-lg text-xs font-medium transition-all disabled:opacity-50">
                {analyzing === `${symbol}_${market}` ? (
                  <Loader2 className="w-3 h-3 animate-spin" />
                ) : <Zap className="w-3 h-3 text-primary" />}
                {symbol}
              </button>
            ))}
          </div>
        </div>

        {/* Filter */}
        <div className="flex gap-2">
          {['all', 'crypto', 'stocks', 'forex'].map((m) => (
            <button key={m} onClick={() => setMarketFilter(m)}
              className={clsx('px-3 py-1 rounded-lg text-xs font-medium capitalize transition-all',
                marketFilter === m ? 'bg-primary text-white' : 'bg-surface text-muted hover:text-white')}>
              {m === 'all' ? 'Toate' : m}
            </button>
          ))}
        </div>

        {/* Selected signal detail */}
        {selected && (
          <div className="card border-primary/50 bg-primary/5 animate-fade-in">
            <div className="flex items-start justify-between mb-3">
              <div>
                <div className="flex items-center gap-2 mb-1">
                  <span className={clsx('px-2 py-0.5 rounded text-xs font-bold',
                    selected.action === 'BUY' ? 'bg-accent/20 text-accent' : selected.action === 'SELL' ? 'bg-danger/20 text-danger' : 'bg-warning/20 text-warning')}>
                    {selected.action}
                  </span>
                  <span className="font-bold">{selected.symbol}</span>
                  <span className="text-xs text-muted capitalize">{selected.market}</span>
                </div>
                <p className="text-xs text-muted">{selected.timeframe} • {selected.confidence}% confidență</p>
              </div>
              <button onClick={() => setSelected(null)} className="text-muted hover:text-white text-lg leading-none">×</button>
            </div>
            <div className="grid grid-cols-3 gap-3 mb-3">
              <div><p className="text-xs text-muted">Intrare</p><p className="num text-sm font-medium">${selected.entryPrice?.toLocaleString()}</p></div>
              <div><p className="text-xs text-muted">Target</p><p className="num text-sm font-medium text-accent">${selected.targetPrice?.toFixed(2)}</p></div>
              <div><p className="text-xs text-muted">Stop Loss</p><p className="num text-sm font-medium text-danger">${selected.stopLoss?.toFixed(2)}</p></div>
            </div>
            <p className="text-xs text-muted leading-relaxed">{selected.reasoning}</p>
          </div>
        )}

        {/* Signals list */}
        {loading ? (
          <div className="flex justify-center py-12">
            <div className="w-8 h-8 border-2 border-primary border-t-transparent rounded-full animate-spin" />
          </div>
        ) : (
          <div className="space-y-2">
            {filtered.map((s) => (
              <button key={s.id} onClick={() => setSelected(s === selected ? null : s)}
                className={clsx('w-full card text-left hover:border-primary/50 transition-all',
                  selected?.id === s.id && 'border-primary/50')}>
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-3">
                    <div className={clsx('px-2 py-0.5 rounded text-xs font-bold w-12 text-center',
                      s.action === 'BUY' ? 'bg-accent/20 text-accent' : 'bg-danger/20 text-danger')}>
                      {s.action}
                    </div>
                    <div>
                      <p className="text-sm font-medium">{s.symbol} <span className="text-muted text-xs capitalize">· {s.market}</span></p>
                      <p className="text-xs text-muted">{s.timeframe} · RR {s.riskRewardRatio?.toFixed(1)}x</p>
                    </div>
                  </div>
                  <div className="text-right">
                    <p className="num text-sm">${s.entryPrice?.toLocaleString()}</p>
                    <div className="flex items-center justify-end gap-1">
                      <div className="h-1.5 w-16 bg-border rounded-full overflow-hidden">
                        <div className="h-full bg-primary rounded-full" style={{ width: `${s.confidence}%` }} />
                      </div>
                      <span className="text-xs text-primary">{s.confidence}%</span>
                    </div>
                  </div>
                </div>
              </button>
            ))}
            {filtered.length === 0 && (
              <div className="flex flex-col items-center justify-center py-12 text-muted">
                <AlertCircle className="w-8 h-8 mb-2" />
                <p>Niciun semnal. Apasă un simbol de mai sus.</p>
              </div>
            )}
          </div>
        )}
      </div>
    </AppLayout>
  );
}
