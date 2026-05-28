import React, { useState } from 'react';
import { Card } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Switch } from '@/components/ui/switch';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Shield, TrendingUp, AlertTriangle } from 'lucide-react';

interface RiskManagementPanelProps {
  config: any;
  onUpdate: (updates: any) => void;
  isLoading?: boolean;
}

export default function RiskManagementPanel({ config, onUpdate, isLoading }: RiskManagementPanelProps) {
  const [breakevenEnabled, setBreakevenEnabled] = useState(config?.breakevenEnabled === 1);
  const [breakevenTrigger, setBreakevenTrigger] = useState(config?.breakevenTrigger || '0.5');
  const [partialTPEnabled, setPartialTPEnabled] = useState(config?.partialTPEnabled === 1);
  const [partialTPPercent, setPartialTPPercent] = useState(config?.partialTPPercent || '0.5');
  const [dailyLossLimit, setDailyLossLimit] = useState(config?.dailyLossLimit || '');

  const handleSave = async () => {
    const updates = {
      breakevenEnabled: breakevenEnabled ? 1 : 0,
      breakevenTrigger,
      partialTPEnabled: partialTPEnabled ? 1 : 0,
      partialTPPercent,
      dailyLossLimit: dailyLossLimit || null,
    };
    await onUpdate(updates);
  };

  return (
    <div className="space-y-6">
      {/* Breakeven Control */}
      <Card className="bg-slate-900/50 border-slate-700/50 p-6">
        <div className="flex items-start justify-between mb-4">
          <div className="flex items-center gap-3">
            <Shield className="w-5 h-5 text-cyan-400" />
            <div>
              <h3 className="text-lg font-semibold text-white">Breakeven Protection</h3>
              <p className="text-slate-400 text-sm">Automatically move stop loss to entry price after profit target</p>
            </div>
          </div>
          <Switch
            checked={breakevenEnabled}
            onCheckedChange={setBreakevenEnabled}
            disabled={isLoading}
          />
        </div>

        {breakevenEnabled && (
          <div className="bg-slate-800/50 rounded p-4 space-y-4">
            <div>
              <Label className="text-slate-300 text-sm">Trigger Profit %</Label>
              <div className="flex items-center gap-2 mt-2">
                <Input
                  type="number"
                  step="0.1"
                  value={breakevenTrigger}
                  onChange={(e) => setBreakevenTrigger(e.target.value)}
                  className="bg-slate-700 border-slate-600 text-white"
                  disabled={isLoading}
                />
                <span className="text-slate-400">%</span>
              </div>
              <p className="text-slate-500 text-xs mt-1">
                Move SL to entry when profit reaches {breakevenTrigger}%
              </p>
            </div>
          </div>
        )}
      </Card>

      {/* Partial Take Profit */}
      <Card className="bg-slate-900/50 border-slate-700/50 p-6">
        <div className="flex items-start justify-between mb-4">
          <div className="flex items-center gap-3">
            <TrendingUp className="w-5 h-5 text-green-400" />
            <div>
              <h3 className="text-lg font-semibold text-white">Partial Take Profit</h3>
              <p className="text-slate-400 text-sm">Close a portion of position at first TP to lock in gains</p>
            </div>
          </div>
          <Switch
            checked={partialTPEnabled}
            onCheckedChange={setPartialTPEnabled}
            disabled={isLoading}
          />
        </div>

        {partialTPEnabled && (
          <div className="bg-slate-800/50 rounded p-4 space-y-4">
            <div>
              <Label className="text-slate-300 text-sm">Close % of Position</Label>
              <div className="flex items-center gap-2 mt-2">
                <Input
                  type="number"
                  step="0.1"
                  min="0"
                  max="100"
                  value={partialTPPercent}
                  onChange={(e) => setPartialTPPercent(e.target.value)}
                  className="bg-slate-700 border-slate-600 text-white"
                  disabled={isLoading}
                />
                <span className="text-slate-400">%</span>
              </div>
              <p className="text-slate-500 text-xs mt-1">
                Close {partialTPPercent}% of position at TP1, let rest run
              </p>
            </div>
          </div>
        )}
      </Card>

      {/* Daily Loss Limit */}
      <Card className="bg-slate-900/50 border-slate-700/50 p-6">
        <div className="flex items-start justify-between mb-4">
          <div className="flex items-center gap-3">
            <AlertTriangle className="w-5 h-5 text-red-400" />
            <div>
              <h3 className="text-lg font-semibold text-white">Daily Loss Limit</h3>
              <p className="text-slate-400 text-sm">Stop trading when daily loss exceeds this threshold</p>
            </div>
          </div>
        </div>

        <div className="bg-slate-800/50 rounded p-4 space-y-4">
          <div>
            <Label className="text-slate-300 text-sm">Daily Loss Limit (USD)</Label>
            <div className="flex items-center gap-2 mt-2">
              <span className="text-slate-400">$</span>
              <Input
                type="number"
                step="0.01"
                value={dailyLossLimit}
                onChange={(e) => setDailyLossLimit(e.target.value)}
                placeholder="Leave empty for no limit"
                className="bg-slate-700 border-slate-600 text-white"
                disabled={isLoading}
              />
            </div>
            <p className="text-slate-500 text-xs mt-1">
              {dailyLossLimit ? `Stop trading when loss reaches $${dailyLossLimit}` : 'No daily loss limit set'}
            </p>
          </div>
        </div>
      </Card>

      {/* Summary */}
      <Card className="bg-gradient-to-r from-cyan-900/20 to-orange-900/20 border border-cyan-500/30 p-6">
        <h4 className="text-white font-semibold mb-3">Risk Management Summary</h4>
        <ul className="space-y-2 text-sm text-slate-300">
          <li className="flex items-center gap-2">
            <span className={`w-2 h-2 rounded-full ${breakevenEnabled ? 'bg-green-400' : 'bg-slate-600'}`}></span>
            Breakeven: {breakevenEnabled ? `Enabled at ${breakevenTrigger}% profit` : 'Disabled'}
          </li>
          <li className="flex items-center gap-2">
            <span className={`w-2 h-2 rounded-full ${partialTPEnabled ? 'bg-green-400' : 'bg-slate-600'}`}></span>
            Partial TP: {partialTPEnabled ? `Enabled - close ${partialTPPercent}%` : 'Disabled'}
          </li>
          <li className="flex items-center gap-2">
            <span className={`w-2 h-2 rounded-full ${dailyLossLimit ? 'bg-green-400' : 'bg-slate-600'}`}></span>
            Daily Limit: {dailyLossLimit ? `$${dailyLossLimit}` : 'No limit'}
          </li>
        </ul>
      </Card>

      <Button
        onClick={handleSave}
        disabled={isLoading}
        className="w-full bg-gradient-to-r from-cyan-600 to-orange-600 hover:from-cyan-700 hover:to-orange-700"
      >
        {isLoading ? 'Saving...' : 'Save Risk Management Settings'}
      </Button>
    </div>
  );
}
