import { useState, useRef, useEffect } from "react";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Send, Loader2, TrendingUp, BarChart3, Shield, ArrowLeft } from "lucide-react";
import { useLocation } from "wouter";

interface Message {
  id: string;
  role: "user" | "assistant";
  content: string;
  timestamp: Date;
}

export default function BotBuilder() {
  const [, setLocation] = useLocation();
  const [messages, setMessages] = useState<Message[]>([
    {
      id: "1",
      role: "assistant",
      content: "Salut! 👋 Sunt Apex AI.\n\nSpune-mi: Ce vrei să tranzacționezi?\n• BTC, ETH, EUR/USD, etc.",
      timestamp: new Date()
    }
  ]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [showBacktest, setShowBacktest] = useState(false);
  const [backtestRunning, setBacktestRunning] = useState(false);
  const [showResults, setShowResults] = useState(false);
  const messagesEndRef = useRef<HTMLDivElement>(null);

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  };

  useEffect(() => {
    scrollToBottom();
  }, [messages]);

  const handleSendMessage = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!input.trim() || loading) return;

    const userMessage: Message = {
      id: Date.now().toString(),
      role: "user",
      content: input,
      timestamp: new Date()
    };

    setMessages(prev => [...prev, userMessage]);
    setInput("");
    setLoading(true);

    // Simulate AI response
    setTimeout(() => {
      const userInput = input.toLowerCase();
      let response = "";

      if (userInput.includes("btc") || userInput.includes("bitcoin")) {
        response = "Perfect! BTC e o alegere bună.\n\nAcum:\n• Ce capital ai?\n• Scalping sau swing trading?\n• Cât profit pe lună?";
      } else if (userInput.includes("eth")) {
        response = "ETH e volatil, bun pentru trading.\n\nSpune-mi:\n• Capital disponibil?\n• Preferință: scalping sau swing?\n• Profit target?";
      } else if (userInput.match(/\d+/)) {
        response = "Bun! Cu acel capital.\n\nAm generat o strategie preliminară:\n\n📊 STRATEGY:\n• Pair: BTC/USDT\n• Timeframe: 15min\n• Risk: 2% per trade\n• Daily limit: 5%\n• Indicators: RSI, MACD, Bollinger Bands\n\nVrei să fac BACKTEST?";
        setShowBacktest(true);
      } else {
        response = "Interesant! 🤔\n\nPot să te ajut mai bine dacă-mi spui:\n• Ce pereche? (BTC, ETH, EUR/USD)\n• Capital?\n• Stil: scalping sau swing?";
      }

      const assistantMessage: Message = {
        id: (Date.now() + 1).toString(),
        role: "assistant",
        content: response,
        timestamp: new Date()
      };

      setMessages(prev => [...prev, assistantMessage]);
      setLoading(false);
    }, 1200);
  };

  const runBacktest = () => {
    setBacktestRunning(true);

    setTimeout(() => {
      const backtestMessage: Message = {
        id: (Date.now() + 2).toString(),
        role: "assistant",
        content: "✅ BACKTEST COMPLET!\n\n📈 Rezultate pe 3 luni:\n• Total trades: 145\n• Win rate: 62%\n• Profit: +$4,850\n• Profit factor: 2.1x\n• Max drawdown: 8.3%\n\nArată bine! 🚀\n\nVrei să faci PAPER TRADING (7 zile)?",
        timestamp: new Date()
      };

      setMessages(prev => [...prev, backtestMessage]);
      setBacktestRunning(false);
      setShowResults(true);
    }, 1500);
  };

  const startPaperTrading = () => {
    const paperMessage: Message = {
      id: (Date.now() + 3).toString(),
      role: "assistant",
      content: "🎯 PAPER TRADING STARTED!\n\nBot-ul simulează tranzacții pe bani fake 7 zile.\n\n📊 Live Results:\n• Current Balance: $10,000\n• Today Profit: +$234\n• Active Trades: 2\n• Win Rate: 65%\n\nMonitorizează pe dashboard! 📈",
      timestamp: new Date()
    };

    setMessages(prev => [...prev, paperMessage]);
  };

  return (
    <div className="min-h-screen bg-black pt-20 pb-10">
      <div className="max-w-6xl mx-auto px-4">
        {/* Header */}
        <div className="flex items-center gap-4 mb-8">
          <Button
            variant="ghost"
            size="sm"
            onClick={() => setLocation("/")}
            className="text-slate-400 hover:text-white"
          >
            <ArrowLeft className="w-4 h-4 mr-2" />
            Back
          </Button>
          <h1 className="text-3xl font-bold text-white">AI Bot Builder</h1>
        </div>

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
                    className="bg-slate-800 border-slate-700 text-white placeholder:text-slate-500"
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

          {/* Actions Panel */}
          <div className="space-y-4">
            <Card className="bg-slate-900 border-slate-800 p-6">
              <h3 className="text-lg font-bold text-white mb-4">📊 Strategy</h3>
              <div className="space-y-3 text-sm">
                <div>
                  <p className="text-slate-400">Pair</p>
                  <p className="text-white font-semibold">BTC/USDT</p>
                </div>
                <div>
                  <p className="text-slate-400">Timeframe</p>
                  <p className="text-white font-semibold">15 min</p>
                </div>
                <div>
                  <p className="text-slate-400">Risk per Trade</p>
                  <p className="text-white font-semibold">2%</p>
                </div>
                <div>
                  <p className="text-slate-400">Indicators</p>
                  <div className="flex flex-wrap gap-2 mt-2">
                    {["RSI", "MACD", "BB"].map((ind) => (
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

              {showBacktest && !showResults && (
                <Button
                  onClick={runBacktest}
                  disabled={backtestRunning}
                  className="w-full mt-4 bg-green-600 hover:bg-green-700"
                >
                  {backtestRunning ? (
                    <>
                      <Loader2 className="w-4 h-4 mr-2 animate-spin" />
                      Running...
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

            {showResults && (
              <Card className="bg-gradient-to-br from-green-900/30 to-slate-900 border-green-600/30 p-6">
                <h3 className="text-lg font-bold text-white mb-4">✅ Results</h3>
                <div className="space-y-3 text-sm">
                  <div className="flex justify-between">
                    <p className="text-slate-400">Trades</p>
                    <p className="text-white font-semibold">145</p>
                  </div>
                  <div className="flex justify-between">
                    <p className="text-slate-400">Win Rate</p>
                    <p className="text-green-400 font-semibold">62%</p>
                  </div>
                  <div className="flex justify-between">
                    <p className="text-slate-400">Profit</p>
                    <p className="text-green-400 font-semibold">+$4,850</p>
                  </div>
                  <div className="flex justify-between">
                    <p className="text-slate-400">Drawdown</p>
                    <p className="text-white font-semibold">8.3%</p>
                  </div>
                </div>

                <Button
                  onClick={startPaperTrading}
                  className="w-full mt-4 bg-blue-600 hover:bg-blue-700"
                >
                  <TrendingUp className="w-4 h-4 mr-2" />
                  Paper Trade 7 Days
                </Button>
              </Card>
            )}

            {!showBacktest && (
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
