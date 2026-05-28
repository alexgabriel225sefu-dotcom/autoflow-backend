import React, { useState, useEffect } from 'react';
import { trpc } from '@/lib/trpc';
import { useAuth } from '@/_core/hooks/useAuth';
import { Card } from '@/components/ui/card';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { Button } from '@/components/ui/button';
import { AlertCircle, TrendingUp, TrendingDown, Zap, BarChart3, Settings, Bell } from 'lucide-react';
import { toast } from 'sonner';
import { useLocation } from 'wouter';

export default function Dashboard() {
  const { user, loading: authLoading } = useAuth();
  const [, setLocation] = useLocation();
  const [activeTab, setActiveTab] = useState('overview');

  // Fetch trading data
  const { data: trades, isLoading: tradesLoading } = trpc.trades.history.useQuery({ limit: 50 });
  const { data: alerts, isLoading: alertsLoading } = trpc.alerts.history.useQuery({ limit: 20 });
  const { data: config } = trpc.config.get.useQuery();
  const { data: paperState } = trpc.paperTrading.state.useQuery();
  const { data: dailySnapshots } = trpc.snapshots.daily.useQuery({ days: 30 });

  if (authLoading) {
    return (
      <div className="flex items-center justify-center min-h-screen">
        <div className="text-center">
          <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-cyan-500 mx-auto mb-4"></div>
          <p className="text-slate-300">Loading dashboard...</p>
        </div>
      </div>
    );
  }

  if (!user) {
    return (
      <div className="flex items-center justify-center min-h-screen">
        <div className="text-center">
          <p className="text-red-400 mb-4">Authentication required</p>
          <Button>Login</Button>
        </div>
      </div>
    );
  }

  // Calculate statistics
  const totalTrades = trades?.length || 0;
  const winningTrades = trades?.filter(t => t.pnl && parseFloat(t.pnl) > 0).length || 0;
  const winRate = totalTrades > 0 ? ((winningTrades / totalTrades) * 100).toFixed(1) : '0';
  const totalPnL = trades?.reduce((sum, t) => sum + (t.pnl ? parseFloat(t.pnl) : 0), 0) || 0;
  const openTrade = trades?.find(t => !t.closedAt);

  return (
    <div className="dashboard-bg">
      <div className="trading-dashboard min-h-screen">
        {/* Header */}
        <header className="border-b border-slate-700/50 bg-slate-900/30 backdrop-blur-md sticky top-0 z-40">
          <div className="max-w-7xl mx-auto px-6 py-6">
            <div className="flex items-center justify-between">
              <div>
                <h1 className="text-4xl font-bold gradient-text">⚡ Apex Trade Bot</h1>
                <p className="text-slate-400 mt-1">Cinematic Algorithmic Trading Dashboard</p>
              </div>
              <div className="flex items-center gap-4">
                <Button
                  onClick={() => setLocation('/alerts')}
                  variant="outline"
                  size="sm"
                  className="gap-2"
                >
                  <Bell className="w-4 h-4" />
                  Alerts
                </Button>
                <Button
                  onClick={() => setLocation('/settings')}
                  variant="outline"
                  size="sm"
                  className="gap-2"
                >
                  <Settings className="w-4 h-4" />
                  Config
                </Button>
              </div>
            </div>
          </div>
        </header>

        {/* Main Content */}
        <main className="max-w-7xl mx-auto px-6 py-8">
          {/* Stats Grid */}
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6 mb-8">
            {/* Balance Card */}
            <div className="stat-card">
              <div className="flex items-center justify-between mb-2">
                <span className="text-slate-400 text-sm font-medium">BALANCE</span>
                <TrendingUp className="w-5 h-5 text-cyan-400" />
              </div>
              <div className="text-3xl font-bold text-white">
                ${paperState?.currentBalance || '0.00'}
              </div>
              <p className="text-slate-400 text-xs mt-2">
                Start: ${paperState?.startBalance || '0.00'}
              </p>
            </div>

            {/* PnL Card */}
            <div className={`stat-card ${totalPnL >= 0 ? 'positive' : 'negative'}`}>
              <div className="flex items-center justify-between mb-2">
                <span className="text-slate-400 text-sm font-medium">TOTAL PnL</span>
                {totalPnL >= 0 ? (
                  <TrendingUp className="w-5 h-5 text-green-400" />
                ) : (
                  <TrendingDown className="w-5 h-5 text-red-400" />
                )}
              </div>
              <div className={`text-3xl font-bold ${totalPnL >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                ${totalPnL.toFixed(2)}
              </div>
              <p className="text-slate-400 text-xs mt-2">
                {totalTrades} trades executed
              </p>
            </div>

            {/* Win Rate Card */}
            <div className="stat-card">
              <div className="flex items-center justify-between mb-2">
                <span className="text-slate-400 text-sm font-medium">WIN RATE</span>
                <BarChart3 className="w-5 h-5 text-orange-400" />
              </div>
              <div className="text-3xl font-bold text-white">{winRate}%</div>
              <p className="text-slate-400 text-xs mt-2">
                {winningTrades} wins / {totalTrades - winningTrades} losses
              </p>
            </div>

            {/* Open Position Card */}
            <div className={`stat-card ${openTrade ? 'positive' : ''}`}>
              <div className="flex items-center justify-between mb-2">
                <span className="text-slate-400 text-sm font-medium">POSITION</span>
                <Zap className="w-5 h-5 text-yellow-400" />
              </div>
              <div className="text-3xl font-bold text-white">
                {openTrade ? openTrade.side : 'NONE'}
              </div>
              <p className="text-slate-400 text-xs mt-2">
                {openTrade ? `@ $${openTrade.entryPrice}` : 'Waiting for signal'}
              </p>
            </div>
          </div>

          {/* Tabs Section */}
          <Tabs value={activeTab} onValueChange={setActiveTab} className="mb-8">
            <TabsList className="bg-slate-900/50 border border-slate-700/50">
              <TabsTrigger value="overview">Overview</TabsTrigger>
              <TabsTrigger value="trades">Trade History</TabsTrigger>
              <TabsTrigger value="alerts">Alerts</TabsTrigger>
              <TabsTrigger value="analysis">Analysis</TabsTrigger>
              <TabsTrigger value="config">Configuration</TabsTrigger>
            </TabsList>

            {/* Overview Tab */}
            <TabsContent value="overview" className="space-y-6">
              <Card className="bg-slate-900/50 border-slate-700/50">
                <div className="p-6">
                  <h3 className="text-lg font-semibold text-white mb-4 flex items-center gap-2">
                    <BarChart3 className="w-5 h-5 text-cyan-400" />
                    Performance Summary
                  </h3>
                  <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                    <div className="bg-slate-800/50 rounded p-4">
                      <p className="text-slate-400 text-sm">Total Trades</p>
                      <p className="text-2xl font-bold text-white">{totalTrades}</p>
                    </div>
                    <div className="bg-slate-800/50 rounded p-4">
                      <p className="text-slate-400 text-sm">Winning Trades</p>
                      <p className="text-2xl font-bold text-green-400">{winningTrades}</p>
                    </div>
                    <div className="bg-slate-800/50 rounded p-4">
                      <p className="text-slate-400 text-sm">Losing Trades</p>
                      <p className="text-2xl font-bold text-red-400">{totalTrades - winningTrades}</p>
                    </div>
                    <div className="bg-slate-800/50 rounded p-4">
                      <p className="text-slate-400 text-sm">Avg Win</p>
                      <p className="text-2xl font-bold text-cyan-400">
                        ${(totalPnL / (winningTrades || 1)).toFixed(2)}
                      </p>
                    </div>
                  </div>
                </div>
              </Card>
            </TabsContent>

            {/* Trade History Tab */}
            <TabsContent value="trades">
              <Card className="bg-slate-900/50 border-slate-700/50">
                <div className="p-6">
                  <h3 className="text-lg font-semibold text-white mb-4">Recent Trades</h3>
                  {tradesLoading ? (
                    <div className="text-center py-8">
                      <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-cyan-500 mx-auto"></div>
                    </div>
                  ) : trades && trades.length > 0 ? (
                    <div className="overflow-x-auto">
                      <table className="trading-table">
                        <thead>
                          <tr>
                            <th>Symbol</th>
                            <th>Side</th>
                            <th>Entry</th>
                            <th>Exit</th>
                            <th>PnL</th>
                            <th>Reason</th>
                            <th>Time</th>
                          </tr>
                        </thead>
                        <tbody>
                          {trades.map((trade) => (
                            <tr key={trade.id}>
                              <td className="font-semibold">{trade.symbol}</td>
                              <td className={trade.side === 'BUY' ? 'text-green-400' : 'text-red-400'}>
                                {trade.side === 'BUY' ? '🟢 LONG' : '🔴 SHORT'}
                              </td>
                              <td>${trade.entryPrice}</td>
                              <td>${trade.exitPrice || '-'}</td>
                              <td className={trade.pnl && parseFloat(trade.pnl) > 0 ? 'win' : 'loss'}>
                                {trade.pnl ? `${parseFloat(trade.pnl) > 0 ? '+' : ''}$${trade.pnl}` : '-'}
                              </td>
                              <td className="text-slate-400 text-xs">{trade.closeReason || 'Open'}</td>
                              <td className="text-slate-400 text-xs">
                                {new Date(trade.openedAt).toLocaleTimeString()}
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  ) : (
                    <div className="text-center py-8 text-slate-400">
                      <AlertCircle className="w-8 h-8 mx-auto mb-2 opacity-50" />
                      <p>No trades yet</p>
                    </div>
                  )}
                </div>
              </Card>
            </TabsContent>

            {/* Alerts Tab */}
            <TabsContent value="alerts">
              <Card className="bg-slate-900/50 border-slate-700/50">
                <div className="p-6">
                  <h3 className="text-lg font-semibold text-white mb-4 flex items-center gap-2">
                    <Bell className="w-5 h-5 text-orange-400" />
                    Alert Log
                  </h3>
                  {alertsLoading ? (
                    <div className="text-center py-8">
                      <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-cyan-500 mx-auto"></div>
                    </div>
                  ) : alerts && alerts.length > 0 ? (
                    <div className="space-y-3 max-h-96 overflow-y-auto">
                      {alerts.map((alert) => (
                        <div key={alert.id} className="bg-slate-800/50 rounded p-4 border border-slate-700/50">
                          <div className="flex items-start justify-between">
                            <div>
                              <p className="text-white font-semibold text-sm">{alert.title}</p>
                              <p className="text-slate-400 text-xs mt-1">{alert.content}</p>
                            </div>
                            <span className="text-slate-500 text-xs whitespace-nowrap ml-4">
                              {new Date(alert.sentAt).toLocaleTimeString()}
                            </span>
                          </div>
                        </div>
                      ))}
                    </div>
                  ) : (
                    <div className="text-center py-8 text-slate-400">
                      <Bell className="w-8 h-8 mx-auto mb-2 opacity-50" />
                      <p>No alerts</p>
                    </div>
                  )}
                </div>
              </Card>
            </TabsContent>

            {/* Analysis Tab */}
            <TabsContent value="analysis">
              <Card className="bg-slate-900/50 border-slate-700/50">
                <div className="p-6">
                  <h3 className="text-lg font-semibold text-white mb-4">Market Analysis</h3>
                  <div className="aspect-video bg-slate-800/50 rounded flex items-center justify-center">
                    <div className="text-center">
                      <BarChart3 className="w-12 h-12 text-slate-600 mx-auto mb-2" />
                      <p className="text-slate-400">TradingView Chart Widget</p>
                      <p className="text-slate-500 text-xs mt-1">Coming soon...</p>
                    </div>
                  </div>
                </div>
              </Card>
            </TabsContent>

            {/* Configuration Tab */}
            <TabsContent value="config">
              <Card className="bg-slate-900/50 border-slate-700/50">
                <div className="p-6">
                  <h3 className="text-lg font-semibold text-white mb-4 flex items-center gap-2">
                    <Settings className="w-5 h-5 text-cyan-400" />
                    Bot Configuration
                  </h3>
                  <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                    <div className="bg-slate-800/50 rounded p-4">
                      <p className="text-slate-400 text-sm">Symbol</p>
                      <p className="text-white font-semibold">{config?.symbol || 'SOLUSDT'}</p>
                    </div>
                    <div className="bg-slate-800/50 rounded p-4">
                      <p className="text-slate-400 text-sm">Timeframe</p>
                      <p className="text-white font-semibold">{config?.timeframe || '5m'}</p>
                    </div>
                    <div className="bg-slate-800/50 rounded p-4">
                      <p className="text-slate-400 text-sm">Risk Per Trade</p>
                      <p className="text-white font-semibold">{config?.riskPerTrade || '0.02'} (2%)</p>
                    </div>
                    <div className="bg-slate-800/50 rounded p-4">
                      <p className="text-slate-400 text-sm">Min Confidence</p>
                      <p className="text-white font-semibold">{config?.minConfidence || 62}%</p>
                    </div>
                    <div className="bg-slate-800/50 rounded p-4">
                      <p className="text-slate-400 text-sm">Stop Loss</p>
                      <p className="text-white font-semibold">{config?.stopLossPct || '0.008'} (0.8%)</p>
                    </div>
                    <div className="bg-slate-800/50 rounded p-4">
                      <p className="text-slate-400 text-sm">Take Profit</p>
                      <p className="text-white font-semibold">{config?.takeProfitPct || '0.016'} (1.6%)</p>
                    </div>
                  </div>
                  <Button className="mt-6 w-full">Edit Configuration</Button>
                </div>
              </Card>
            </TabsContent>
          </Tabs>
        </main>
      </div>
    </div>
  );
}
