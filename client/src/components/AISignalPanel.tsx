import React, { useState } from 'react';
import { Card } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Spinner } from '@/components/ui/spinner';
import { Brain, Zap, TrendingUp, TrendingDown } from 'lucide-react';
import { trpc } from '@/lib/trpc';
import { toast } from 'sonner';

interface AISignalPanelProps {
  symbol: string;
  currentPrice?: number;
}

export default function AISignalPanel({ symbol, currentPrice }: AISignalPanelProps) {
  const [signal, setSignal] = useState<{
    action: 'BUY' | 'SELL' | 'HOLD';
    confidence: number;
    criteriaScore: number;
    reasoning: string;
    timestamp: Date;
  } | null>(null);
  const [isAnalyzing, setIsAnalyzing] = useState(false);

  const handleAnalyzeNow = async () => {
    setIsAnalyzing(true);
    try {
      // Simulate LLM analysis
      const actions: ('BUY' | 'SELL' | 'HOLD')[] = ['BUY', 'SELL', 'HOLD'];
      const mockSignal = {
        action: actions[Math.floor(Math.random() * 3)],
        confidence: Math.floor(Math.random() * 40 + 60), // 60-100
        criteriaScore: Math.floor(Math.random() * 5 + 1), // 1-5
        reasoning: 'Market shows strong confluence of Turtle Breakout and RSI oversold conditions. Multiple timeframe alignment suggests potential reversal. Risk/reward ratio favorable at current levels.',
        timestamp: new Date(),
      };
      setSignal(mockSignal as typeof signal);
      toast.success('Market analysis complete');
    } catch (error) {
      toast.error('Analysis failed');
    } finally {
      setIsAnalyzing(false);
    }
  };

  const getSignalColor = (action: string) => {
    switch (action) {
      case 'BUY':
        return 'text-green-400';
      case 'SELL':
        return 'text-red-400';
      default:
        return 'text-yellow-400';
    }
  };

  const getSignalBgColor = (action: string) => {
    switch (action) {
      case 'BUY':
        return 'bg-green-900/20 border-green-500/30';
      case 'SELL':
        return 'bg-red-900/20 border-red-500/30';
      default:
        return 'bg-yellow-900/20 border-yellow-500/30';
    }
  };

  return (
    <div className="space-y-6">
      {/* Current Signal */}
      <Card className={`border p-6 ${signal ? getSignalBgColor(signal.action) : 'bg-slate-900/50 border-slate-700/50'}`}>
        <div className="flex items-start justify-between mb-4">
          <div className="flex items-center gap-3">
            <Brain className="w-6 h-6 text-cyan-400" />
            <div>
              <h3 className="text-lg font-semibold text-white">AI Market Signal</h3>
              <p className="text-slate-400 text-sm">{symbol} • Real-time Analysis</p>
            </div>
          </div>
        </div>

        {signal ? (
          <div className="space-y-4">
            {/* Signal Action */}
            <div className="flex items-center justify-between">
              <span className="text-slate-300">Current Action:</span>
              <div className={`text-3xl font-bold ${getSignalColor(signal.action)} flex items-center gap-2`}>
                {signal.action === 'BUY' && <TrendingUp className="w-6 h-6" />}
                {signal.action === 'SELL' && <TrendingDown className="w-6 h-6" />}
                {signal.action === 'HOLD' && <Zap className="w-6 h-6" />}
                {signal.action}
              </div>
            </div>

            {/* Confidence Meter */}
            <div>
              <div className="flex items-center justify-between mb-2">
                <span className="text-slate-300 text-sm">Confidence</span>
                <span className="text-white font-semibold">{signal.confidence}%</span>
              </div>
              <div className="w-full bg-slate-700 rounded-full h-2">
                <div
                  className="bg-gradient-to-r from-cyan-500 to-orange-500 h-2 rounded-full transition-all"
                  style={{ width: `${signal.confidence}%` }}
                ></div>
              </div>
            </div>

            {/* Criteria Score */}
            <div>
              <div className="flex items-center justify-between mb-2">
                <span className="text-slate-300 text-sm">Criteria Score</span>
                <span className="text-white font-semibold">{signal.criteriaScore}/5</span>
              </div>
              <div className="flex gap-1">
                {[1, 2, 3, 4, 5].map((i) => (
                  <div
                    key={i}
                    className={`flex-1 h-2 rounded ${
                      i <= signal.criteriaScore
                        ? 'bg-gradient-to-r from-cyan-500 to-orange-500'
                        : 'bg-slate-700'
                    }`}
                  ></div>
                ))}
              </div>
            </div>

            {/* Reasoning */}
            <div className="bg-slate-800/50 rounded p-4 border border-slate-700/50">
              <p className="text-slate-300 text-sm leading-relaxed">{signal.reasoning}</p>
            </div>

            {/* Timestamp */}
            <p className="text-slate-500 text-xs">
              Last updated: {signal.timestamp.toLocaleTimeString()}
            </p>
          </div>
        ) : (
          <div className="text-center py-8">
            <Brain className="w-12 h-12 text-slate-600 mx-auto mb-3" />
            <p className="text-slate-400 mb-4">No analysis yet. Click "Analyze Now" to get started.</p>
          </div>
        )}
      </Card>

      {/* Analyze Button */}
      <Button
        onClick={handleAnalyzeNow}
        disabled={isAnalyzing}
        className="w-full bg-gradient-to-r from-cyan-600 to-orange-600 hover:from-cyan-700 hover:to-orange-700 text-white font-semibold py-6 text-lg"
      >
        {isAnalyzing ? (
          <>
            <Spinner className="w-4 h-4 mr-2" />
            Analyzing Market...
          </>
        ) : (
          <>
            <Zap className="w-5 h-5 mr-2" />
            Analyze Now
          </>
        )}
      </Button>

      {/* Strategy Confluence Indicators */}
      <Card className="bg-slate-900/50 border-slate-700/50 p-6">
        <h4 className="text-white font-semibold mb-4 flex items-center gap-2">
          <Zap className="w-5 h-5 text-orange-400" />
          Strategy Confluence
        </h4>
        <div className="space-y-3">
          <div className="flex items-center justify-between bg-slate-800/50 rounded p-3">
            <span className="text-slate-300">Turtle Breakout</span>
            <div className="flex items-center gap-2">
              <div className="w-2 h-2 bg-green-400 rounded-full"></div>
              <span className="text-green-400 text-sm font-semibold">STRONG</span>
            </div>
          </div>
          <div className="flex items-center justify-between bg-slate-800/50 rounded p-3">
            <span className="text-slate-300">Livermore Structure</span>
            <div className="flex items-center gap-2">
              <div className="w-2 h-2 bg-yellow-400 rounded-full"></div>
              <span className="text-yellow-400 text-sm font-semibold">MODERATE</span>
            </div>
          </div>
          <div className="flex items-center justify-between bg-slate-800/50 rounded p-3">
            <span className="text-slate-300">Soros Momentum</span>
            <div className="flex items-center gap-2">
              <div className="w-2 h-2 bg-red-400 rounded-full"></div>
              <span className="text-red-400 text-sm font-semibold">WEAK</span>
            </div>
          </div>
        </div>
      </Card>
    </div>
  );
}
