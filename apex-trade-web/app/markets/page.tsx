'use client';
import { useEffect, useState } from 'react';
import AppLayout from '@/components/layout/AppLayout';
import { marketsApi } from '@/lib/api';
import { TrendingUp, TrendingDown, RefreshCw } from 'lucide-react';
import clsx from 'clsx';

type Market = 'crypto' | 'stocks' | 'forex';

interface Asset {
  symbol: string;
  name?: string;
  price: number;
  change24h: number;
  changePercent24h?: number;
  volume24h?: number;
  marketCap?: number;
}

export default function MarketsPage() {
  const [market, setMarket] = useState<Market>('crypto');
  const [assets, setAssets] = useState<Asset[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);

  async function load(m: Market, silent = false) {
    if (!silent) setLoading(true);
    else setRefreshing(true);
    try {
      const fetchers = { crypto: marketsApi.getCrypto, stocks: marketsApi.getStocks, forex: marketsApi.getForex };
      const res = await fetchers[m]();
      setAssets(res.data);
    } catch {
      setAssets([]);
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }

  useEffect(() => { load(market); }, [market]);

  const tabs: { key: Market; label: string; emoji: string }[] = [
    { key: 'crypto', label: 'Crypto', emoji: '₿' },
    { key: 'stocks', label: 'Acțiuni', emoji: '📈' },
    { key: 'forex', label: 'Forex', emoji: '💱' },
  ];

  return (
    <AppLayout>
      <div className="p-4 md:p-6 space-y-4 animate-fade-in">
        <div className="flex items-center justify-between">
          <h1 className="text-2xl font-bold">Piețe</h1>
          <button onClick={() => load(market, true)}
            className={clsx('p-2 text-muted hover:text-white transition-colors', refreshing && 'animate-spin')}>
            <RefreshCw className="w-4 h-4" />
          </button>
        </div>

        {/* Tabs */}
        <div className="flex gap-2 bg-surface rounded-xl p-1">
          {tabs.map(({ key, label, emoji }) => (
            <button key={key} onClick={() => setMarket(key)}
              className={clsx('flex-1 py-2 px-3 rounded-lg text-sm font-medium transition-all',
                market === key ? 'bg-primary text-white' : 'text-muted hover:text-white')}>
              {emoji} {label}
            </button>
          ))}
        </div>

        {/* Table */}
        {loading ? (
          <div className="flex justify-center py-16">
            <div className="w-8 h-8 border-2 border-primary border-t-transparent rounded-full animate-spin" />
          </div>
        ) : (
          <div className="card p-0 overflow-hidden">
            <div className="grid grid-cols-3 px-4 py-2 border-b border-border text-xs text-muted font-medium">
              <span>ACTIV</span>
              <span className="text-right">PREȚ</span>
              <span className="text-right">24H</span>
            </div>
            <div className="divide-y divide-border">
              {assets.map((asset, i) => {
                const positive = asset.change24h >= 0;
                return (
                  <div key={i} className="grid grid-cols-3 items-center px-4 py-3 hover:bg-surface-2 transition-colors">
                    <div>
                      <p className="font-semibold text-sm">{asset.symbol}</p>
                      {asset.name && <p className="text-xs text-muted">{asset.name}</p>}
                    </div>
                    <p className="text-right num text-sm font-medium">
                      ${asset.price?.toLocaleString('en', { minimumFractionDigits: market === 'forex' ? 4 : 2, maximumFractionDigits: market === 'forex' ? 5 : 2 })}
                    </p>
                    <div className={clsx('flex items-center justify-end gap-1 text-sm num font-medium',
                      positive ? 'text-accent' : 'text-danger')}>
                      {positive ? <TrendingUp className="w-3 h-3" /> : <TrendingDown className="w-3 h-3" />}
                      {positive ? '+' : ''}{asset.change24h?.toFixed(2)}%
                    </div>
                  </div>
                );
              })}
              {assets.length === 0 && (
                <p className="text-muted text-sm text-center py-8">Nu există date disponibile</p>
              )}
            </div>
          </div>
        )}
      </div>
    </AppLayout>
  );
}
