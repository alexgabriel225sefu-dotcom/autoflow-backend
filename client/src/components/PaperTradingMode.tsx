import React, { useState } from 'react';
import { Card } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Switch } from '@/components/ui/switch';
import { Zap, RotateCcw, TrendingUp, TrendingDown } from 'lucide-react';
import { trpc } from '@/lib/trpc';
import { toast } from 'sonner';

interface PaperTradingModeProps {
  config: any;
  paperState: any;
  onUpdate: (updates: any) => void;
}

export default function PaperTradingMode({ config, paperState, onUpdate }: PaperTradingModeProps) {
  const [paperModeEnabled, setPaperModeEnabled] = useState(config?.paperTradingMode === 1);
  const [isResetting, setIsResetting] = useState(false);

  const handleTogglePaperMode = async (enabled: boolean) => {
    setPaperModeEnabled(enabled);
    await onUpdate({
      paperTradingMode: enabled ? 1 : 0,
    });
    toast.success(`Paper trading ${enabled ? 'enabled' : 'disabled'}`);
  };

  const handleResetPaperTrading = async () => {
    setIsResetting(true);
    try {
      const initialBalance = '10000';
      await onUpdate({
        currentBalance: initialBalance,
        startBalance: initialBalance,
        totalTrades: 0,
        wins: 0,
        losses: 0,
        maxDrawdown: '0',
        peakBalance: initialBalance,
      });
      toast.success('Paper trading account reset');
    } catch (error) {
      toast.error('Reset failed');
    } finally {
      setIsResetting(false);
    }
  };

  const currentBalance = parseFloat(paperState?.currentBalance || '10000');
  const startBalance = parseFloat(paperState?.startBalance || '10000');
  const totalReturn = ((currentBalance - startBalance) / startBalance) * 100;
  const totalTrades = paperState?.totalTrades || 0;
  const wins = paperState?.wins || 0;
  const losses = paperState?.losses || 0;
  const winRate = totalTrades > 0 ? ((wins / totalTrades) * 100).toFixed(1) : '0';
  const maxDrawdown = paperState?.maxDrawdown || '0';

  return (
    <div className="space-y-6">
      {/* Paper Trading Toggle */}
      <Card className="bg-slate-900/50 border-slate-700/50 p-6">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <Zap className="w-6 h-6 text-yellow-400" />
            <div>
              <h3 className="text-lg font-semibold text-white">Paper Trading Mode</h3>
              <p className="text-slate-400 text-sm">Simulate trades without real money</p>
            </div>
          </div>
          <Switch
            checked={paperModeEnabled}
            onCheckedChange={handleTogglePaperMode}
          />
        </div>
      </Card>

      {paperModeEnabled && (
        <>
          {/* Performance Stats */}
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
            {/* Current Balance */}
            <Card className="bg-slate-900/50 border-slate-700/50 p-4">
              <p className="text-slate-400 text-xs uppercase font-semibold mb-2">Current Balance</p>
              <p className="text-2xl font-bold text-white">${currentBalance.toFixed(2)}</p>
              <p className={`text-xs mt-2 ${totalReturn >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                {totalReturn >= 0 ? '+' : ''}{totalReturn.toFixed(2)}%
              </p>
            </Card>

            {/* Total Trades */}
            <Card className="bg-slate-900/50 border-slate-700/50 p-4">
              <p className="text-slate-400 text-xs uppercase font-semibold mb-2">Total Trades</p>
              <p className="text-2xl font-bold text-white">{totalTrades}</p>
              <p className="text-xs text-slate-400 mt-2">
                {wins} wins • {losses} losses
              </p>
            </Card>

            {/* Win Rate */}
            <Card className="bg-slate-900/50 border-slate-700/50 p-4">
              <p className="text-slate-400 text-xs uppercase font-semibold mb-2">Win Rate</p>
              <p className="text-2xl font-bold text-white">{winRate}%</p>
              <p className="text-xs text-slate-400 mt-2">
                {wins}/{totalTrades} winning trades
              </p>
            </Card>

            {/* Max Drawdown */}
            <Card className="bg-slate-900/50 border-slate-700/50 p-4">
              <p className="text-slate-400 text-xs uppercase font-semibold mb-2">Max Drawdown</p>
              <p className="text-2xl font-bold text-red-400">{maxDrawdown}%</p>
              <p className="text-xs text-slate-400 mt-2">Peak to trough decline</p>
            </Card>
          </div>

          {/* Performance Chart Placeholder */}
          <Card className="bg-slate-900/50 border-slate-700/50 p-6">
            <h4 className="text-white font-semibold mb-4">Equity Curve</h4>
            <div className="aspect-video bg-slate-800/50 rounded flex items-center justify-center">
              <div className="text-center">
                <TrendingUp className="w-12 h-12 text-slate-600 mx-auto mb-2" />
                <p className="text-slate-400">Performance chart coming soon</p>
              </div>
            </div>
          </Card>

          {/* Reset Button */}
          <Button
            onClick={handleResetPaperTrading}
            disabled={isResetting}
            variant="outline"
            className="w-full"
          >
            <RotateCcw className="w-4 h-4 mr-2" />
            {isResetting ? 'Resetting...' : 'Reset Paper Trading Account'}
          </Button>

          {/* Info Box */}
          <Card className="bg-blue-900/20 border border-blue-500/30 p-4">
            <p className="text-blue-300 text-sm">
              💡 Paper trading allows you to test your bot strategy without risking real capital. All trades are simulated using the configured risk parameters.
            </p>
          </Card>
        </>
      )}

      {!paperModeEnabled && (
        <Card className="bg-slate-900/50 border-slate-700/50 p-6 text-center">
          <p className="text-slate-400">Enable paper trading mode to start simulating trades</p>
        </Card>
      )}
    </div>
  );
}
