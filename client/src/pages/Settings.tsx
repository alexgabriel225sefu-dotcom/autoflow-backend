import React, { useState } from 'react';
import { trpc } from '@/lib/trpc';
import { useAuth } from '@/_core/hooks/useAuth';
import { Card } from '@/components/ui/card';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Settings as SettingsIcon, Save } from 'lucide-react';
import { toast } from 'sonner';
import RiskManagementPanel from '@/components/RiskManagementPanel';
import AISignalPanel from '@/components/AISignalPanel';
import PaperTradingMode from '@/components/PaperTradingMode';

export default function Settings() {
  const { user } = useAuth();
  const { data: config, isLoading: configLoading } = trpc.config.get.useQuery();
  const { data: paperState } = trpc.paperTrading.state.useQuery();
  const updateConfigMutation = trpc.config.update.useMutation();
  const updatePaperStateMutation = trpc.paperTrading.update.useMutation();

  const [formData, setFormData] = useState({
    symbol: config?.symbol || 'SOLUSDT',
    timeframe: config?.timeframe || '5m',
    riskPerTrade: config?.riskPerTrade || '0.02',
    stopLossPct: config?.stopLossPct || '0.008',
    takeProfitPct: config?.takeProfitPct || '0.016',
    minConfidence: config?.minConfidence || 62,
  });

  const handleInputChange = (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) => {
    const { name, value } = e.target;
    setFormData((prev) => ({
      ...prev,
      [name]: name === 'minConfidence' ? parseInt(value) : value,
    }));
  };

  const handleSaveBasicConfig = async () => {
    try {
      await updateConfigMutation.mutateAsync(formData);
      toast.success('Configuration saved successfully');
    } catch (error) {
      toast.error('Failed to save configuration');
    }
  };

  const handleUpdateRiskManagement = async (updates: any) => {
    try {
      await updateConfigMutation.mutateAsync(updates);
      toast.success('Risk management settings updated');
    } catch (error) {
      toast.error('Failed to update risk management');
    }
  };

  const handleUpdatePaperTrading = async (updates: any) => {
    try {
      await updatePaperStateMutation.mutateAsync(updates);
      toast.success('Paper trading settings updated');
    } catch (error) {
      toast.error('Failed to update paper trading');
    }
  };

  if (configLoading) {
    return (
      <div className="flex items-center justify-center min-h-screen">
        <div className="text-center">
          <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-cyan-500 mx-auto mb-4"></div>
          <p className="text-slate-300">Loading settings...</p>
        </div>
      </div>
    );
  }

  return (
    <div className="dashboard-bg">
      <div className="trading-dashboard min-h-screen">
        {/* Header */}
        <header className="border-b border-slate-700/50 bg-slate-900/30 backdrop-blur-md sticky top-0 z-40">
          <div className="max-w-7xl mx-auto px-6 py-6">
            <h1 className="text-4xl font-bold gradient-text flex items-center gap-3">
              <SettingsIcon className="w-8 h-8" />
              Bot Configuration
            </h1>
            <p className="text-slate-400 mt-1">Manage trading parameters and risk settings</p>
          </div>
        </header>

        {/* Main Content */}
        <main className="max-w-7xl mx-auto px-6 py-8">
          <Tabs defaultValue="basic" className="space-y-6">
            <TabsList className="bg-slate-900/50 border border-slate-700/50">
              <TabsTrigger value="basic">Basic Settings</TabsTrigger>
              <TabsTrigger value="risk">Risk Management</TabsTrigger>
              <TabsTrigger value="ai">AI Signals</TabsTrigger>
              <TabsTrigger value="paper">Paper Trading</TabsTrigger>
            </TabsList>

            {/* Basic Settings Tab */}
            <TabsContent value="basic">
              <Card className="bg-slate-900/50 border-slate-700/50 p-8">
                <h2 className="text-2xl font-bold text-white mb-6">Trading Parameters</h2>

                <div className="grid grid-cols-1 md:grid-cols-2 gap-6 mb-8">
                  {/* Symbol */}
                  <div>
                    <Label className="text-slate-300 mb-2 block">Trading Symbol</Label>
                    <Input
                      name="symbol"
                      value={formData.symbol}
                      onChange={handleInputChange}
                      className="bg-slate-700 border-slate-600 text-white"
                      placeholder="e.g., SOLUSDT"
                    />
                    <p className="text-slate-500 text-xs mt-1">The trading pair to trade</p>
                  </div>

                  {/* Timeframe */}
                  <div>
                    <Label className="text-slate-300 mb-2 block">Timeframe</Label>
                    <select
                      name="timeframe"
                      value={formData.timeframe}
                      onChange={handleInputChange}
                      className="w-full bg-slate-700 border border-slate-600 text-white rounded px-3 py-2"
                    >
                      <option value="1m">1 Minute</option>
                      <option value="5m">5 Minutes</option>
                      <option value="15m">15 Minutes</option>
                      <option value="1h">1 Hour</option>
                      <option value="4h">4 Hours</option>
                      <option value="1d">1 Day</option>
                    </select>
                    <p className="text-slate-500 text-xs mt-1">Candle timeframe for analysis</p>
                  </div>

                  {/* Risk Per Trade */}
                  <div>
                    <Label className="text-slate-300 mb-2 block">Risk Per Trade (%)</Label>
                    <Input
                      name="riskPerTrade"
                      type="number"
                      step="0.01"
                      value={formData.riskPerTrade}
                      onChange={handleInputChange}
                      className="bg-slate-700 border-slate-600 text-white"
                    />
                    <p className="text-slate-500 text-xs mt-1">Percentage of balance to risk per trade</p>
                  </div>

                  {/* Stop Loss % */}
                  <div>
                    <Label className="text-slate-300 mb-2 block">Stop Loss (%)</Label>
                    <Input
                      name="stopLossPct"
                      type="number"
                      step="0.001"
                      value={formData.stopLossPct}
                      onChange={handleInputChange}
                      className="bg-slate-700 border-slate-600 text-white"
                    />
                    <p className="text-slate-500 text-xs mt-1">Distance from entry to stop loss</p>
                  </div>

                  {/* Take Profit % */}
                  <div>
                    <Label className="text-slate-300 mb-2 block">Take Profit (%)</Label>
                    <Input
                      name="takeProfitPct"
                      type="number"
                      step="0.001"
                      value={formData.takeProfitPct}
                      onChange={handleInputChange}
                      className="bg-slate-700 border-slate-600 text-white"
                    />
                    <p className="text-slate-500 text-xs mt-1">Distance from entry to take profit</p>
                  </div>

                  {/* Min Confidence */}
                  <div>
                    <Label className="text-slate-300 mb-2 block">Min Confidence (%)</Label>
                    <Input
                      name="minConfidence"
                      type="number"
                      min="0"
                      max="100"
                      value={formData.minConfidence}
                      onChange={handleInputChange}
                      className="bg-slate-700 border-slate-600 text-white"
                    />
                    <p className="text-slate-500 text-xs mt-1">Minimum AI confidence to enter trade</p>
                  </div>
                </div>

                <Button
                  onClick={handleSaveBasicConfig}
                  disabled={updateConfigMutation.isPending}
                  className="bg-gradient-to-r from-cyan-600 to-orange-600 hover:from-cyan-700 hover:to-orange-700 text-white font-semibold py-6 px-8"
                >
                  <Save className="w-4 h-4 mr-2" />
                  {updateConfigMutation.isPending ? 'Saving...' : 'Save Settings'}
                </Button>
              </Card>
            </TabsContent>

            {/* Risk Management Tab */}
            <TabsContent value="risk">
              <RiskManagementPanel
                config={config}
                onUpdate={handleUpdateRiskManagement}
                isLoading={updateConfigMutation.isPending}
              />
            </TabsContent>

            {/* AI Signals Tab */}
            <TabsContent value="ai">
              <AISignalPanel symbol={formData.symbol} />
            </TabsContent>

            {/* Paper Trading Tab */}
            <TabsContent value="paper">
              <PaperTradingMode
                config={config}
                paperState={paperState}
                onUpdate={handleUpdatePaperTrading}
              />
            </TabsContent>
          </Tabs>
        </main>
      </div>
    </div>
  );
}
