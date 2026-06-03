import { useState, useRef, useEffect } from "react";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Send, Loader2, TrendingUp, BarChart3, Shield } from "lucide-react";

interface Message {
  id: string;
  role: "user" | "assistant";
  content: string;
  timestamp: Date;
}

interface Strategy {
  name: string;
  exchange: string;
  pairs: string[];
  timeframe: string;
  riskPerTrade: number;
  dailyLossLimit: number;
  indicators: string[];
  backtestResult?: {
    totalTrades: number;
    winRate: number;
    profit: number;
    profitFactor: number;
    maxDrawdown: number;
  };
}

export default function BotBuilder() {
  const [messages, setMessages] = useState<Message[]>([
    {
      id: "1",
      role: "assistant",
      content: "Salut! 👋 Sunt Apex AI. Vreau să-ți ajut să creezi botul perfect pentru tine.\n\nSpune-mi: Ce vrei să tranzacționezi? (BTC, ETH, EUR/USD, etc.)",
      timestamp: new Date()
    }
  ]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [strategy, setStrategy] = useState<Strategy | null>(null);
  const [backtestRunning, setBacktestRunning] = useState(false);
  const messagesEndRef = useRef<HTMLDivElement>(null);

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  };

  useEffect(() => {
    scrollToBottom();
  }, [messages]);

  const handleSendMessage = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!input.trim()) return;

    const userMessage: Message = {
      id: Date.now().toString(),
      role: "user",
      content: input,
      timestamp: new Date()
    };

    setMessages(prev => [...prev, userMessage]);
    setInput("");
    setLoading(true);

    // Simulate AI response with strategy building
    setTimeout(() => {
      let response = "";
      const userInput = input.toLowerCase();

      // Simulate conversational flow
      if (userInput.includes("btc") || userInput.includes("bitcoin")) {
        response = "Perfect! BTC e o alegere bună.\n\nAcum, spune-mi:\n• Ce capital ai?\n• Scalping (quick trades) sau swing trading (hold 1-7 zile)?\n• Cât profit țintești pe lună?";
      } else if (userInput.includes("eth") || userInput.includes("ethereum")) {
        response = "ETH e volatil, bun pentru trading.\n\nContinuă:\n• Capital disponibil?\n• Preferință: scalping sau swing?\n• Profit target?";
      } else if (userInput.includes("$") || userInput.match(/\d+k?/)) {
        response = "Bun! Cu acel capital.\n\nAcum:\n• Vrei max 3 trades/zi sau nelimitat?\n• Risk per trade: 1%, 2%, sau 3%?\n• Stop loss: fix sau ATR-based?";
      } else if (userInput.includes("trade") || userInput.includes("scalp")) {
        response = "Scalping e bun pentru volatilitate.\n\nAm generat o strategie preliminară:\n\n📊 STRATEGY DRAFT:\n• Pair: BTC/USDT\n• Timeframe: 15min\n• Indicators: RSI, MACD, Bollinger Bands\n• Risk: 2% per trade\n• Daily limit: 5%\n\nVrei să fac BACKTEST pe date istorice?";
        
        // Set strategy when ready
        setStrategy({
          name: "BTC Scalping Strategy",
          exchange: "Binance",
          pairs: ["BTCUSDT"],
          timeframe: "15min",
          riskPerTrade: 2,
          dailyLossLimit: 5,
          indicators: ["RSI", "MACD", "Bollinger Bands", "EMA"]
        });
      } else {
        response = "Interesant! 🤔\n\nPot să te ajut mai bine dacă-mi spui:\n• Ce pereche vrei? (BTC, ETH, EUR/USD, etc.)\n• Capital?\n• Stil: scalping sau swing?\n\nMerge?";
      }

      const assistantMessage: Message = {
        id: (Date.now() + 1).toString(),
        role: "assistant",
        content: response,
        timestamp: new Date()
      };

      setMessages(prev => [...prev, assistantMessage]);
      setLoading(false);
    }, 1500);
  };

  const runBacktest = () => {
    if (!strategy) return;

    setBacktestRunning(true);

    // Simulate backtest
    setTimeout(() => {
      setStrategy(prev => prev ? {
        ...prev,
        backtestResult: {
          totalTrades: 145,
          winRate: 62,
          profit: 4850,
          profitFactor: 2.1,
          maxDrawdown: 8.3
        }
      } : null);

      const backtestMessage: Message = {
        id: (Date.now() + 2).toString(),
        role: "assistant",
        content: "✅ BACKTEST COMPLET!\n\n📈 Rezultate pe 3 luni (istoric):\n• Total trades: 145\n• Win rate: 62%\n• Profit: +$4,850\n• Profit factor: 2.1x\n• Max drawdown: 8.3%\n\nArată bine! 🚀\n\nVrei să faci PAPER TRADING (7 zile simulare live)?",
        timestamp: new Date()
      };

      setMessages(prev => [...prev, backtestMessage]);
      setBacktestRunning(false);
    }, 2000);
  };

  return (
    <div className="min-h-screen bg-black pt-20">
      <div className="max-w-6xl mx-auto px-4 py-8">
        <div className="grid lg:grid-cols-3 gap-6">
          {/* Chat Area */}
          <div className="lg:col-span-2">
            <Card className="bg-slate-900 border-slate-800 h-[600px] flex flex-col">
              {/* Messages */}
              <div className="flex-1 overflow-y-auto p-6 space-y-4">
                {messages.map((msg) => (
                  <div
                    key={msg.id}
                    className={`flex ${msg.role === "user" ? "justify-end" : "justify-start"}`}
                  >
                    <div
                      className={`max-w-xs lg:max-w-md px-4 py-3 rounded-lg ${
                        msg.role === "user"
                          ? "bg-blue-600 text-white"
                          : "bg-slate-800 text-slate-100"
                      }`}
                    >
                      <p className="text-sm whitespace-pre-wrap">{msg.content}</p>
                      <span className="text-xs opacity-70 mt-2 block">
                        {msg.timestamp.toLocaleTimeString()}
                      </span>
                    </div>
                  </div>
                ))}
                {loading && (
                  <div className="flex justify-start">
                    <div className="bg-slate-800 text-slate-100 px-4 py-3 rounded-lg">
                      <Loader2 className="w-4 h-4 animate-spin" />
                    </div>
                  </div>
                )}
                <div ref={messagesEndRef} />
              </div>

              {/* Input */}
              <div className="border-t border-slate-800 p-4">
                <form onSubmit={handleSendMessage} className="flex gap-2">
                  <Input
                    value={input}
                    onChange={(e) => setInput(e.target.value)}
                    placeholder="Scrie răspunsul tău..."
                    className="bg-slate-800 border-slate-700 text-white"
                    disabled={loading}
                  />
                  <Button
                    type="submit"
                    disabled={loading || !input.trim()}
                    className="bg-blue-600 hover:bg-blue-700"
                  >
                    <Send className="w-4 h-4" />
                  </Button>
                </form>
              </div>
            </Card>
          </div>

          {/* Strategy Panel */}
          <div className="space-y-4">
            {strategy ? (
              <>
                <Card className="bg-slate-900 border-slate-800 p-6">
                  <h3 className="text-lg font-bold text-white mb-4">📊 Strategy</h3>
                  <div className="space-y-3 text-sm">
                    <div>
                      <p className="text-slate-400">Pair</p>
                      <p className="text-white font-semibold">{strategy.pairs.join(", ")}</p>
                    </div>
                    <div>
                      <p className="text-slate-400">Timeframe</p>
                      <p className="text-white font-semibold">{strategy.timeframe}</p>
                    </div>
                    <div>
                      <p className="text-slate-400">Risk per Trade</p>
                      <p className="text-white font-semibold">{strategy.riskPerTrade}%</p>
                    </div>
                    <div>
                      <p className="text-slate-400">Daily Loss Limit</p>
                      <p className="text-white font-semibold">{strategy.dailyLossLimit}%</p>
                    </div>
                    <div>
                      <p className="text-slate-400">Indicators</p>
                      <div className="flex flex-wrap gap-2 mt-2">
                        {strategy.indicators.map((ind) => (
                          <span
                            key={ind}
                            className="bg-blue-600/30 text-blue-300 px-2 py-1 rounded text-xs"
                          >
                            {ind}
                          </span>
                        ))}
                      </div>
                    </div>
                  </div>

                  {!strategy.backtestResult && (
                    <Button
                      onClick={runBacktest}
                      disabled={backtestRunning}
                      className="w-full mt-4 bg-green-600 hover:bg-green-700"
                    >
                      {backtestRunning ? (
                        <>
                          <Loader2 className="w-4 h-4 mr-2 animate-spin" />
                          Backtest...
                        </>
                      ) : (
                        <>
                          <BarChart3 className="w-4 h-4 mr-2" />
                          Run Backtest
                        </>
                      )}
                    </Button>
                  )}
                </Card>

                {strategy.backtestResult && (
                  <Card className="bg-gradient-to-br from-green-900/30 to-slate-900 border-green-600/30 p-6">
                    <h3 className="text-lg font-bold text-white mb-4">✅ Backtest Results</h3>
                    <div className="space-y-3 text-sm">
                      <div className="flex justify-between">
                        <p className="text-slate-400">Total Trades</p>
                        <p className="text-white font-semibold">{strategy.backtestResult.totalTrades}</p>
                      </div>
                      <div className="flex justify-between">
                        <p className="text-slate-400">Win Rate</p>
                        <p className="text-green-400 font-semibold">{strategy.backtestResult.winRate}%</p>
                      </div>
                      <div className="flex justify-between">
                        <p className="text-slate-400">Profit</p>
                        <p className="text-green-400 font-semibold">+${strategy.backtestResult.profit}</p>
                      </div>
                      <div className="flex justify-between">
                        <p className="text-slate-400">Profit Factor</p>
                        <p className="text-white font-semibold">{strategy.backtestResult.profitFactor}x</p>
                      </div>
                      <div className="flex justify-between">
                        <p className="text-slate-400">Max Drawdown</p>
                        <p className="text-white font-semibold">{strategy.backtestResult.maxDrawdown}%</p>
                      </div>
                    </div>

                    <Button className="w-full mt-4 bg-blue-600 hover:bg-blue-700">
                      <TrendingUp className="w-4 h-4 mr-2" />
                      Paper Trade 7 Days
                    </Button>
                  </Card>
                )}
              </>
            ) : (
              <Card className="bg-slate-900 border-slate-800 p-6 text-center">
                <Shield className="w-12 h-12 text-slate-600 mx-auto mb-4" />
                <p className="text-slate-400 text-sm">
                  Răspunde la întrebări pentru a genera o strategie
                </p>
              </Card>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
