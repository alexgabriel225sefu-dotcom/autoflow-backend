import { useAuth } from "@/_core/hooks/useAuth";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Check, ChevronDown, Zap, TrendingUp, Shield, Rocket, Play } from "lucide-react";
import { getLoginUrl } from "@/const";
import { useState } from "react";

export default function Home() {
  const { user, isAuthenticated, logout } = useAuth();
  const [expandedFaq, setExpandedFaq] = useState<number | null>(null);
  const [showDemo, setShowDemo] = useState(false);

  const faqItems = [
    {
      question: "How long does the setup take?",
      answer: "The complete setup takes about 30 minutes. You'll learn to configure the bot, connect to Binance, and deploy it on Railway in this tutorial."
    },
    {
      question: "Do I need coding experience?",
      answer: "No! The setup is completely no-code. We provide step-by-step instructions and a pre-configured bot ready to deploy."
    },
    {
      question: "Can I use this with real money?",
      answer: "Yes, but we recommend testing with paper trading first. Start with small amounts and scale gradually as you gain confidence."
    },
    {
      question: "What exchanges are supported?",
      answer: "The bot supports Binance (crypto and forex pairs). Support for other exchanges can be added."
    },
    {
      question: "Is there a money-back guarantee?",
      answer: "Yes! 30-day money-back guarantee if you're not satisfied. No questions asked."
    },
    {
      question: "How often do I need to monitor the bot?",
      answer: "The bot runs 24/7 automatically. We recommend checking in daily to review trades and performance metrics."
    }
  ];

  const features = [
    {
      icon: Zap,
      title: "AI-Powered Signals",
      description: "Multi-indicator strategy (RSI, MACD, Bollinger Bands) for accurate entry/exit signals"
    },
    {
      icon: Shield,
      title: "Strict Risk Management",
      description: "2% risk per trade, 5% daily loss limit, and dynamic stop losses protect your capital"
    },
    {
      icon: TrendingUp,
      title: "Proven Strategy",
      description: "Backtested on 2+ years of data with 60%+ win rate in various market conditions"
    },
    {
      icon: Rocket,
      title: "Easy Deployment",
      description: "Deploy on Railway in minutes. No server setup required, runs 24/7 automatically"
    }
  ];

  return (
    <div className="min-h-screen bg-gradient-to-b from-slate-900 via-slate-800 to-slate-900">
      {/* Navigation */}
      <nav className="fixed top-0 w-full bg-slate-900/80 backdrop-blur-md border-b border-slate-700 z-50">
        <div className="max-w-6xl mx-auto px-4 py-4 flex justify-between items-center">
          <div className="text-2xl font-bold text-white">
            Apex <span className="text-blue-500">Bot</span>
          </div>
          <div className="flex gap-4 items-center">
            {isAuthenticated ? (
              <>
                <span className="text-slate-300">{user?.name}</span>
                <Button onClick={logout} variant="outline" size="sm">
                  Logout
                </Button>
              </>
            ) : (
              <Button asChild size="sm">
                <a href={getLoginUrl()}>Login</a>
              </Button>
            )}
          </div>
        </div>
      </nav>

      {/* Hero Section */}
      <section className="pt-32 pb-20 px-4">
        <div className="max-w-4xl mx-auto text-center">
          <div className="inline-block mb-6 px-4 py-2 bg-blue-500/10 border border-blue-500/20 rounded-full">
            <span className="text-blue-400 text-sm font-semibold">🚀 AI Trading Automation</span>
          </div>
          
          <h1 className="text-5xl md:text-6xl font-bold text-white mb-6 leading-tight">
            Build Your AI Trading Bot in <span className="text-transparent bg-clip-text bg-gradient-to-r from-blue-400 to-cyan-400">30 Minutes</span>
          </h1>
          
          <p className="text-xl text-slate-300 mb-8 leading-relaxed">
            Automate your crypto & forex trading with a professional AI-powered bot. 
            Multi-indicator strategy, strict risk management, and 24/7 trading. 
            No coding required.
          </p>

          <div className="flex flex-col sm:flex-row gap-4 justify-center mb-12">
            <Button 
              size="lg" 
              className="bg-blue-600 hover:bg-blue-700 text-white px-8"
              onClick={() => setShowDemo(true)}
            >
              <Play className="w-4 h-4 mr-2" />
              Watch Demo
            </Button>
            <Button size="lg" variant="outline" className="border-slate-600 text-white hover:bg-slate-800">
              Learn More
            </Button>
          </div>

          {/* Trust Badges */}
          <div className="flex flex-wrap justify-center gap-6 text-sm text-slate-400">
            <div className="flex items-center gap-2">
              <Check className="w-4 h-4 text-green-500" />
              <span>30-Day Money Back</span>
            </div>
            <div className="flex items-center gap-2">
              <Check className="w-4 h-4 text-green-500" />
              <span>Lifetime Access</span>
            </div>
            <div className="flex items-center gap-2">
              <Check className="w-4 h-4 text-green-500" />
              <span>24/7 Support</span>
            </div>
          </div>
        </div>
      </section>

      {/* Demo Modal */}
      {showDemo && (
        <div className="fixed inset-0 bg-black/50 z-40 flex items-center justify-center p-4">
          <div className="bg-slate-900 rounded-lg max-w-2xl w-full">
            <div className="flex justify-between items-center p-6 border-b border-slate-700">
              <h3 className="text-xl font-bold text-white">Trading Bot Demo - How It Works</h3>
              <button 
                onClick={() => setShowDemo(false)}
                className="text-slate-400 hover:text-white text-2xl"
              >
                ×
              </button>
            </div>
            <div className="p-6">
              <div className="bg-slate-800 rounded-lg p-8 mb-6">
                <div className="space-y-4">
                  <div className="flex items-start gap-4">
                    <div className="flex-shrink-0 w-8 h-8 rounded-full bg-blue-600 text-white flex items-center justify-center font-bold">1</div>
                    <div>
                      <h4 className="text-white font-semibold">Bot Configuration</h4>
                      <p className="text-slate-400 text-sm">Set API keys, indicators (RSI, MACD, Bollinger Bands), and risk rules</p>
                    </div>
                  </div>
                  
                  <div className="flex items-start gap-4">
                    <div className="flex-shrink-0 w-8 h-8 rounded-full bg-blue-600 text-white flex items-center justify-center font-bold">2</div>
                    <div>
                      <h4 className="text-white font-semibold">Market Analysis</h4>
                      <p className="text-slate-400 text-sm">Bot analyzes price charts with multiple technical indicators in real-time</p>
                    </div>
                  </div>

                  <div className="flex items-start gap-4">
                    <div className="flex-shrink-0 w-8 h-8 rounded-full bg-blue-600 text-white flex items-center justify-center font-bold">3</div>
                    <div>
                      <h4 className="text-white font-semibold">Trade Signals</h4>
                      <p className="text-slate-400 text-sm">When conditions align, bot generates BUY or SELL signals automatically</p>
                    </div>
                  </div>

                  <div className="flex items-start gap-4">
                    <div className="flex-shrink-0 w-8 h-8 rounded-full bg-blue-600 text-white flex items-center justify-center font-bold">4</div>
                    <div>
                      <h4 className="text-white font-semibold">Trade Execution</h4>
                      <p className="text-slate-400 text-sm">Bot enters position with calculated size based on risk management rules</p>
                    </div>
                  </div>

                  <div className="flex items-start gap-4">
                    <div className="flex-shrink-0 w-8 h-8 rounded-full bg-blue-600 text-white flex items-center justify-center font-bold">5</div>
                    <div>
                      <h4 className="text-white font-semibold">Risk Management</h4>
                      <p className="text-slate-400 text-sm">Stop loss and take profit levels protect capital and lock in gains</p>
                    </div>
                  </div>

                  <div className="flex items-start gap-4">
                    <div className="flex-shrink-0 w-8 h-8 rounded-full bg-green-600 text-white flex items-center justify-center font-bold">✓</div>
                    <div>
                      <h4 className="text-white font-semibold">24/7 Automation</h4>
                      <p className="text-slate-400 text-sm">Bot runs continuously, executing trades while you sleep or work</p>
                    </div>
                  </div>
                </div>
              </div>

              <div className="bg-slate-800/50 rounded-lg p-4">
                <h4 className="text-white font-semibold mb-3">Key Features:</h4>
                <ul className="text-slate-300 text-sm space-y-2">
                  <li>✓ Multi-indicator strategy (RSI, MACD, Bollinger Bands, EMA)</li>
                  <li>✓ Paper trading mode for risk-free testing</li>
                  <li>✓ Real money mode with strict risk management (2% per trade)</li>
                  <li>✓ 62% historical win rate on backtested data</li>
                  <li>✓ Deploy on Railway - runs 24/7 automatically</li>
                  <li>✓ Monitor all trades and performance in real-time</li>
                </ul>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Features Section */}
      <section className="py-20 px-4 bg-slate-800/50">
        <div className="max-w-6xl mx-auto">
          <h2 className="text-4xl font-bold text-white text-center mb-4">What You Get</h2>
          <p className="text-slate-400 text-center mb-12 max-w-2xl mx-auto">
            Everything you need to start automated trading in minutes
          </p>

          <div className="grid md:grid-cols-2 lg:grid-cols-4 gap-6">
            {features.map((feature, idx) => {
              const Icon = feature.icon;
              return (
                <Card key={idx} className="bg-slate-900 border-slate-700 p-6">
                  <Icon className="w-8 h-8 text-blue-500 mb-4" />
                  <h3 className="text-lg font-semibold text-white mb-2">{feature.title}</h3>
                  <p className="text-slate-400 text-sm">{feature.description}</p>
                </Card>
              );
            })}
          </div>
        </div>
      </section>

      {/* How It Works */}
      <section className="py-20 px-4">
        <div className="max-w-4xl mx-auto">
          <h2 className="text-4xl font-bold text-white text-center mb-12">How It Works</h2>

          <div className="space-y-8">
            {[
              {
                step: 1,
                title: "Purchase & Access",
                description: "Get instant access to the complete trading bot code, setup guide, and 30-minute video tutorial"
              },
              {
                step: 2,
                title: "Follow Setup Tutorial",
                description: "Watch the step-by-step video showing how to configure the bot, connect to Binance, and deploy on Railway"
              },
              {
                step: 3,
                title: "Deploy & Trade",
                description: "Launch your bot with one click. It runs 24/7 automatically, executing trades based on AI signals"
              }
            ].map((item) => (
              <div key={item.step} className="flex gap-6">
                <div className="flex-shrink-0">
                  <div className="flex items-center justify-center h-12 w-12 rounded-lg bg-blue-600 text-white font-bold">
                    {item.step}
                  </div>
                </div>
                <div>
                  <h3 className="text-xl font-semibold text-white mb-2">{item.title}</h3>
                  <p className="text-slate-400">{item.description}</p>
                </div>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* Pricing Section */}
      <section className="py-20 px-4 bg-slate-800/50">
        <div className="max-w-2xl mx-auto text-center">
          <h2 className="text-4xl font-bold text-white mb-4">Simple Pricing</h2>
          <p className="text-slate-400 mb-12">One-time payment, lifetime access</p>

          <Card className="bg-slate-900 border-blue-500/30 p-12">
            <div className="text-5xl font-bold text-white mb-2">$197</div>
            <p className="text-slate-400 mb-8">One-time payment</p>

            <ul className="space-y-4 mb-8 text-left">
              <li className="flex items-center gap-3 text-white">
                <Check className="w-5 h-5 text-green-500" />
                Complete trading bot source code
              </li>
              <li className="flex items-center gap-3 text-white">
                <Check className="w-5 h-5 text-green-500" />
                30-minute setup video tutorial
              </li>
              <li className="flex items-center gap-3 text-white">
                <Check className="w-5 h-5 text-green-500" />
                Lifetime updates & improvements
              </li>
              <li className="flex items-center gap-3 text-white">
                <Check className="w-5 h-5 text-green-500" />
                Email support & documentation
              </li>
              <li className="flex items-center gap-3 text-white">
                <Check className="w-5 h-5 text-green-500" />
                30-day money-back guarantee
              </li>
            </ul>

            <Button size="lg" className="w-full bg-blue-600 hover:bg-blue-700 text-white mb-4" disabled>
              Coming Soon - Payment Integration
            </Button>
            <p className="text-slate-500 text-sm">Stripe integration coming soon</p>
          </Card>
        </div>
      </section>

      {/* FAQ Section */}
      <section className="py-20 px-4">
        <div className="max-w-3xl mx-auto">
          <h2 className="text-4xl font-bold text-white text-center mb-12">Frequently Asked Questions</h2>

          <div className="space-y-4">
            {faqItems.map((item, idx) => (
              <div key={idx} className="border border-slate-700 rounded-lg overflow-hidden">
                <button
                  onClick={() => setExpandedFaq(expandedFaq === idx ? null : idx)}
                  className="w-full px-6 py-4 flex justify-between items-center hover:bg-slate-800/50 transition-colors"
                >
                  <span className="text-lg font-semibold text-white text-left">{item.question}</span>
                  <ChevronDown
                    className={`w-5 h-5 text-slate-400 transition-transform ${
                      expandedFaq === idx ? "rotate-180" : ""
                    }`}
                  />
                </button>
                {expandedFaq === idx && (
                  <div className="px-6 py-4 bg-slate-800/30 border-t border-slate-700">
                    <p className="text-slate-300">{item.answer}</p>
                  </div>
                )}
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* CTA Section */}
      <section className="py-20 px-4 bg-gradient-to-r from-blue-600/20 to-cyan-600/20 border-y border-slate-700">
        <div className="max-w-3xl mx-auto text-center">
          <h2 className="text-4xl font-bold text-white mb-6">Ready to Automate Your Trading?</h2>
          <p className="text-xl text-slate-300 mb-8">
            Join traders using Apex Bot to automate their strategies and trade 24/7
          </p>
          <Button size="lg" className="bg-blue-600 hover:bg-blue-700 text-white px-12" disabled>
            Get Started - Coming Soon
          </Button>
          <p className="text-slate-400 text-sm mt-4">30-day money-back guarantee • No questions asked</p>
        </div>
      </section>

      {/* Footer */}
      <footer className="bg-slate-900 border-t border-slate-700 py-12 px-4">
        <div className="max-w-6xl mx-auto">
          <div className="grid md:grid-cols-4 gap-8 mb-8">
            <div>
              <h3 className="text-white font-bold mb-4">Apex Bot</h3>
              <p className="text-slate-400 text-sm">AI-powered trading automation for crypto & forex</p>
            </div>
            <div>
              <h4 className="text-white font-semibold mb-4">Product</h4>
              <ul className="space-y-2 text-slate-400 text-sm">
                <li><a href="#" className="hover:text-white">Features</a></li>
                <li><a href="#" className="hover:text-white">Pricing</a></li>
                <li><a href="#" className="hover:text-white">Documentation</a></li>
              </ul>
            </div>
            <div>
              <h4 className="text-white font-semibold mb-4">Support</h4>
              <ul className="space-y-2 text-slate-400 text-sm">
                <li><a href="#" className="hover:text-white">Help Center</a></li>
                <li><a href="#" className="hover:text-white">Contact</a></li>
                <li><a href="#" className="hover:text-white">Status</a></li>
              </ul>
            </div>
            <div>
              <h4 className="text-white font-semibold mb-4">Legal</h4>
              <ul className="space-y-2 text-slate-400 text-sm">
                <li><a href="#" className="hover:text-white">Terms</a></li>
                <li><a href="#" className="hover:text-white">Privacy</a></li>
                <li><a href="#" className="hover:text-white">Disclaimer</a></li>
              </ul>
            </div>
          </div>

          <div className="border-t border-slate-700 pt-8">
            <p className="text-slate-400 text-sm text-center">
              © 2026 Apex Bot. All rights reserved. | Disclaimer: Trading involves risk. Past performance is not indicative of future results.
            </p>
          </div>
        </div>
      </footer>
    </div>
  );
}
