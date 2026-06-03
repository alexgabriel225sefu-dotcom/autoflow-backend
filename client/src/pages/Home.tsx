import { useAuth } from "@/_core/hooks/useAuth";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Check, ChevronDown, Zap, TrendingUp, Shield, Rocket, Play, Star, Users, DollarSign, BarChart3 } from "lucide-react";
import { getLoginUrl } from "@/const";
import { useLocation } from "wouter";
import { useState } from "react";

export default function Home() {
  const { user, isAuthenticated, logout } = useAuth();
  const [, setLocation] = useLocation();
  const [expandedFaq, setExpandedFaq] = useState<number | null>(null);

  const testimonials = [
    {
      name: "Alex M.",
      role: "Crypto Trader",
      text: "Generată strategia în 5 minute. Backtest arată +45% în 3 luni. Worth every penny!",
      rating: 5
    },
    {
      name: "Maria T.",
      role: "Forex Trader",
      text: "Nu am experiență în coding. Botul merge perfect. Profit consistent.",
      rating: 5
    },
    {
      name: "John D.",
      role: "Day Trader",
      text: "Best $297 I spent. Bot execută trades mai bine decât eu manual.",
      rating: 5
    }
  ];

  const stats = [
    { label: "Active Bots", value: "2,847", icon: Rocket },
    { label: "Avg Profit", value: "+34%", icon: TrendingUp },
    { label: "Users", value: "1,200+", icon: Users },
    { label: "Total Traded", value: "$12.3M", icon: DollarSign }
  ];

  const faqItems = [
    {
      question: "Cum generez strategia?",
      answer: "Simplu: intri în chat, spui ce vrei (BTC, 3 trades/zi, 2% risk), AI-ul generează strategie, faci backtest, și asta e!"
    },
    {
      question: "Ce se întâmplă dacă nu e profitabil?",
      answer: "Faci paper trading 7 zile. Dacă nu merge, nu plătești. Doar dacă e profitabil în simulare, mergi live."
    },
    {
      question: "Pot folosi pe Binance?",
      answer: "Da! Binance, Bybit, Kraken - orice exchange cu API. Conectezi cheile și gata."
    },
    {
      question: "E sigur?",
      answer: "Botul are strict risk management: 2% per trade, 5% daily loss limit, stop loss automat."
    },
    {
      question: "Pot modifica strategia?",
      answer: "Da! Oricând. Generezi altă strategie, faci backtest, și switch-uiești botul."
    },
    {
      question: "Suport?",
      answer: "Email support + documentație completă. Răspund în 24h."
    }
  ];

  const features = [
    {
      icon: Zap,
      title: "AI Strategy Builder",
      description: "Conversație naturală → Strategie profesională în minute"
    },
    {
      icon: BarChart3,
      title: "Backtest Instant",
      description: "Vezi cum ar fi funcționat pe date istorice (2+ ani)"
    },
    {
      icon: Shield,
      title: "Risk Management",
      description: "2% per trade, daily limits, stop loss automat"
    },
    {
      icon: TrendingUp,
      title: "Paper Trading",
      description: "Test 7 zile pe bani fake - fără risc"
    },
    {
      icon: Rocket,
      title: "One-Click Deploy",
      description: "Bot merge 24/7 pe exchange-ul tău"
    },
    {
      icon: Users,
      title: "Live Monitoring",
      description: "Dashboard cu toate tranzacțiile și profit/loss"
    }
  ];

  return (
    <div className="min-h-screen bg-black">
      {/* Navigation */}
      <nav className="fixed top-0 w-full bg-black/80 backdrop-blur-md border-b border-slate-800 z-50">
        <div className="max-w-7xl mx-auto px-4 py-4 flex justify-between items-center">
          <div className="text-2xl font-bold">
            <span className="text-white">Apex</span>
            <span className="text-blue-500 ml-2">Bot</span>
          </div>
          <div className="flex gap-4 items-center">
            <Button variant="ghost" size="sm" onClick={() => setLocation("/builder")}>
              Builder
            </Button>
            {isAuthenticated ? (
              <>
                <span className="text-slate-300">{user?.name}</span>
                <Button onClick={logout} variant="outline" size="sm">
                  Logout
                </Button>
              </>
            ) : (
              <Button asChild size="sm" className="bg-blue-600 hover:bg-blue-700">
                <a href={getLoginUrl()}>Login</a>
              </Button>
            )}
          </div>
        </div>
      </nav>

      {/* Hero Section */}
      <section className="pt-40 pb-20 px-4 bg-gradient-to-b from-slate-950 to-black">
        <div className="max-w-5xl mx-auto text-center">
          <div className="inline-flex items-center gap-2 mb-6 px-4 py-2 bg-blue-500/10 border border-blue-500/30 rounded-full">
            <Star className="w-4 h-4 text-blue-400" />
            <span className="text-blue-400 text-sm font-semibold">Trusted by 1,200+ Traders</span>
          </div>
          
          <h1 className="text-6xl md:text-7xl font-bold text-white mb-6 leading-tight">
            Generează-ți botul în <span className="text-transparent bg-clip-text bg-gradient-to-r from-blue-400 via-cyan-400 to-blue-500">5 minute</span>
          </h1>
          
          <p className="text-xl text-slate-300 mb-8 max-w-2xl mx-auto leading-relaxed">
            Conversație AI → Strategie → Backtest → Paper Trading → Deploy Live
            <br />
            <span className="text-sm text-slate-400 mt-2 block">Fără o linie de cod. Fără experiență necesară.</span>
          </p>

          <div className="flex flex-col sm:flex-row gap-4 justify-center mb-12">
            <Button 
              size="lg" 
              className="bg-gradient-to-r from-blue-600 to-cyan-600 hover:from-blue-700 hover:to-cyan-700 text-white px-8 text-lg"
              onClick={() => setLocation("/builder")}
            >
              <Play className="w-5 h-5 mr-2" />
              Încearcă Gratuit
            </Button>
            <Button size="lg" variant="outline" className="border-slate-600 text-white hover:bg-slate-900 px-8 text-lg">
              Vezi Demo
            </Button>
          </div>

          {/* Trust Badges */}
          <div className="flex flex-wrap justify-center gap-8 text-sm text-slate-400 mb-12">
            <div className="flex items-center gap-2">
              <Check className="w-4 h-4 text-green-500" />
              <span>Paper Trading Gratuit</span>
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

          {/* Stats */}
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mt-12">
            {stats.map((stat, idx) => {
              const Icon = stat.icon;
              return (
                <div key={idx} className="bg-slate-900/50 border border-slate-800 rounded-lg p-4">
                  <Icon className="w-6 h-6 text-blue-500 mx-auto mb-2" />
                  <div className="text-2xl font-bold text-white">{stat.value}</div>
                  <div className="text-xs text-slate-400">{stat.label}</div>
                </div>
              );
            })}
          </div>
        </div>
      </section>

      {/* How It Works */}
      <section className="py-20 px-4 bg-black">
        <div className="max-w-5xl mx-auto">
          <h2 className="text-4xl font-bold text-white text-center mb-4">Cum Funcționează</h2>
          <p className="text-slate-400 text-center mb-12">5 pași simpli la botul tău profesional</p>

          <div className="grid md:grid-cols-5 gap-4">
            {[
              { step: 1, title: "Chat", desc: "Spui ce vrei" },
              { step: 2, title: "Strategie", desc: "AI generează" },
              { step: 3, title: "Backtest", desc: "Vezi rezultate" },
              { step: 4, title: "Paper Trade", desc: "Test 7 zile" },
              { step: 5, title: "Deploy", desc: "Bot live" }
            ].map((item, idx) => (
              <div key={idx} className="relative">
                <div className="bg-slate-900 border border-slate-800 rounded-lg p-6 text-center">
                  <div className="w-12 h-12 rounded-full bg-blue-600 text-white flex items-center justify-center font-bold mx-auto mb-4">
                    {item.step}
                  </div>
                  <h3 className="text-white font-semibold mb-2">{item.title}</h3>
                  <p className="text-slate-400 text-sm">{item.desc}</p>
                </div>
                {idx < 4 && (
                  <div className="hidden md:block absolute top-1/2 -right-2 w-4 h-0.5 bg-gradient-to-r from-blue-600 to-transparent"></div>
                )}
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* Features */}
      <section className="py-20 px-4 bg-slate-950">
        <div className="max-w-6xl mx-auto">
          <h2 className="text-4xl font-bold text-white text-center mb-4">Features Profesionale</h2>
          <p className="text-slate-400 text-center mb-12">Tot ce ai nevoie pentru trading automat</p>

          <div className="grid md:grid-cols-2 lg:grid-cols-3 gap-6">
            {features.map((feature, idx) => {
              const Icon = feature.icon;
              return (
                <Card key={idx} className="bg-slate-900 border-slate-800 p-6 hover:border-blue-500/50 transition-colors">
                  <Icon className="w-8 h-8 text-blue-500 mb-4" />
                  <h3 className="text-lg font-semibold text-white mb-2">{feature.title}</h3>
                  <p className="text-slate-400 text-sm">{feature.description}</p>
                </Card>
              );
            })}
          </div>
        </div>
      </section>

      {/* Testimonials */}
      <section className="py-20 px-4 bg-black">
        <div className="max-w-5xl mx-auto">
          <h2 className="text-4xl font-bold text-white text-center mb-12">Ce Spun Utilizatorii</h2>

          <div className="grid md:grid-cols-3 gap-6">
            {testimonials.map((testimonial, idx) => (
              <Card key={idx} className="bg-slate-900 border-slate-800 p-6">
                <div className="flex gap-1 mb-4">
                  {[...Array(testimonial.rating)].map((_, i) => (
                    <Star key={i} className="w-4 h-4 fill-yellow-500 text-yellow-500" />
                  ))}
                </div>
                <p className="text-slate-300 mb-4 italic">"{testimonial.text}"</p>
                <div>
                  <p className="text-white font-semibold">{testimonial.name}</p>
                  <p className="text-slate-400 text-sm">{testimonial.role}</p>
                </div>
              </Card>
            ))}
          </div>
        </div>
      </section>

      {/* Pricing */}
      <section className="py-20 px-4 bg-slate-950">
        <div className="max-w-2xl mx-auto text-center">
          <h2 className="text-4xl font-bold text-white mb-4">Pricing Simplu</h2>
          <p className="text-slate-400 mb-12">One-time payment. Lifetime access.</p>

          <Card className="bg-gradient-to-br from-slate-900 to-slate-800 border-blue-500/30 p-12">
            <div className="text-6xl font-bold text-white mb-2">$297</div>
            <p className="text-slate-400 mb-8">One-time. Fără subscripție.</p>

            <ul className="space-y-4 mb-8 text-left">
              <li className="flex items-center gap-3 text-white">
                <Check className="w-5 h-5 text-green-500 flex-shrink-0" />
                <span>AI Strategy Builder (unlimited)</span>
              </li>
              <li className="flex items-center gap-3 text-white">
                <Check className="w-5 h-5 text-green-500 flex-shrink-0" />
                <span>Backtest Engine (2+ ani date)</span>
              </li>
              <li className="flex items-center gap-3 text-white">
                <Check className="w-5 h-5 text-green-500 flex-shrink-0" />
                <span>Paper Trading (7 zile gratuit)</span>
              </li>
              <li className="flex items-center gap-3 text-white">
                <Check className="w-5 h-5 text-green-500 flex-shrink-0" />
                <span>Deploy pe Binance/Bybit/Kraken</span>
              </li>
              <li className="flex items-center gap-3 text-white">
                <Check className="w-5 h-5 text-green-500 flex-shrink-0" />
                <span>Live Monitoring Dashboard</span>
              </li>
              <li className="flex items-center gap-3 text-white">
                <Check className="w-5 h-5 text-green-500 flex-shrink-0" />
                <span>Lifetime Updates & Support</span>
              </li>
            </ul>

            <Button size="lg" className="w-full bg-gradient-to-r from-blue-600 to-cyan-600 hover:from-blue-700 hover:to-cyan-700 text-white text-lg">
              Cumpără Acum
            </Button>

            <p className="text-slate-500 text-sm mt-4">
              30 zile money-back guarantee dacă nu ești mulțumit
            </p>
          </Card>
        </div>
      </section>

      {/* FAQ */}
      <section className="py-20 px-4 bg-black">
        <div className="max-w-3xl mx-auto">
          <h2 className="text-4xl font-bold text-white text-center mb-12">Întrebări Frecvente</h2>

          <div className="space-y-4">
            {faqItems.map((item, idx) => (
              <div key={idx} className="border border-slate-800 rounded-lg overflow-hidden hover:border-slate-700 transition-colors">
                <button
                  onClick={() => setExpandedFaq(expandedFaq === idx ? null : idx)}
                  className="w-full px-6 py-4 flex justify-between items-center hover:bg-slate-900/50 transition-colors"
                >
                  <span className="text-lg font-semibold text-white text-left">{item.question}</span>
                  <ChevronDown
                    className={`w-5 h-5 text-slate-400 transition-transform flex-shrink-0 ${
                      expandedFaq === idx ? "rotate-180" : ""
                    }`}
                  />
                </button>
                {expandedFaq === idx && (
                  <div className="px-6 py-4 bg-slate-900/30 border-t border-slate-800">
                    <p className="text-slate-300">{item.answer}</p>
                  </div>
                )}
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* CTA Final */}
      <section className="py-20 px-4 bg-gradient-to-r from-blue-600/20 to-cyan-600/20 border-y border-slate-800">
        <div className="max-w-3xl mx-auto text-center">
          <h2 className="text-4xl font-bold text-white mb-6">Gata să Automatizezi Trading-ul?</h2>
          <p className="text-xl text-slate-300 mb-8">
            Generează strategie în 5 minute. Paper trade 7 zile. Deploy live.
          </p>
          <Button size="lg" className="bg-gradient-to-r from-blue-600 to-cyan-600 hover:from-blue-700 hover:to-cyan-700 text-white px-12 text-lg">
            Încearcă Gratuit Acum
          </Button>
        </div>
      </section>

      {/* Footer */}
      <footer className="bg-slate-950 border-t border-slate-800 py-12 px-4">
        <div className="max-w-6xl mx-auto">
          <div className="grid md:grid-cols-4 gap-8 mb-8">
            <div>
              <h3 className="text-white font-bold mb-4">Apex Bot</h3>
              <p className="text-slate-400 text-sm">AI-powered trading automation platform</p>
            </div>
            <div>
              <h4 className="text-white font-semibold mb-4">Product</h4>
              <ul className="space-y-2 text-slate-400 text-sm">
                <li><a href="#" className="hover:text-white">Features</a></li>
                <li><a href="#" className="hover:text-white">Pricing</a></li>
                <li><a href="#" className="hover:text-white">Docs</a></li>
              </ul>
            </div>
            <div>
              <h4 className="text-white font-semibold mb-4">Company</h4>
              <ul className="space-y-2 text-slate-400 text-sm">
                <li><a href="#" className="hover:text-white">About</a></li>
                <li><a href="#" className="hover:text-white">Blog</a></li>
                <li><a href="#" className="hover:text-white">Contact</a></li>
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

          <div className="border-t border-slate-800 pt-8">
            <p className="text-slate-400 text-sm text-center">
              © 2026 Apex Bot. All rights reserved. | Disclaimer: Trading involves risk.
            </p>
          </div>
        </div>
      </footer>
    </div>
  );
}
