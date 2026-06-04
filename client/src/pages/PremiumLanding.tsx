import { useEffect, useRef, useState } from 'react';
import { Button } from '@/components/ui/button';
import {
  TrendingUp, Zap, Shield, Bot, BarChart3, Bell,
  CheckCircle2, ArrowRight, ChevronDown, Star,
  Globe, RefreshCcw, Target, Clock, DollarSign,
  Activity, AlertTriangle, Layers, Brain
} from 'lucide-react';

const TICKER_ITEMS = [
  { symbol: 'SOL/USDT', price: '$182.40', change: '+4.2%', up: true },
  { symbol: 'XRP/USDT', price: '$0.624', change: '+2.8%', up: true },
  { symbol: 'DOGE/USDT', price: '$0.183', change: '-1.1%', up: false },
  { symbol: 'TRX/USDT', price: '$0.267', change: '+3.5%', up: true },
  { symbol: 'ADA/USDT', price: '$0.449', change: '+1.9%', up: true },
];

const FEATURES = [
  {
    icon: Brain,
    title: 'Claude AI + Groq Fallback',
    desc: 'Decizii de tranzacționare alimentate de Claude (Anthropic) cu fallback automat pe Groq — niciodată fără semnal.',
  },
  {
    icon: Layers,
    title: '5 Strategii Legendare',
    desc: 'Turtle Breakout, Livermore Structure, Soros Momentum, Druckenmiller Sizing și Seykota Risk — toate combinate.',
  },
  {
    icon: Globe,
    title: 'Multi-Exchange cu Failover',
    desc: 'Bybit principal cu fallback automat pe Binance și OKX — datele nu se opresc niciodată.',
  },
  {
    icon: Activity,
    title: 'Scanner 5 Simboluri',
    desc: 'Scanează simultan SOL, XRP, DOGE, TRX, ADA la fiecare 15 minute pe 400 de lumânări de date.',
  },
  {
    icon: Shield,
    title: 'Risk Management Profesionist',
    desc: '2% risc per trade, Stop Loss 1%, Take Profit 2% (R:R 1:2), trailing stop și protecție drawdown -20%.',
  },
  {
    icon: BarChart3,
    title: '8 Indicatori Tehnici Preciși',
    desc: 'RSI Wilder, MACD, Bollinger Bands, EMA 20/50/200, ATR, StochRSI și detectare divergențe.',
  },
  {
    icon: Bell,
    title: 'Alerte Telegram în Timp Real',
    desc: 'Primești instant notificări pentru fiecare trade: BUY, SELL, CLOSE cu motivație AI și nivel de încredere.',
  },
  {
    icon: Target,
    title: 'Paper Trading Mode',
    desc: 'Testează strategia fără risc real. Verifică performanța botului pe contul tău virtual înainte să activezi live.',
  },
];

const STRATEGIES = [
  { name: 'Turtle', trader: 'Richard Dennis', rule: 'Breakout pe 20 lumânări cu confirmare volum' },
  { name: 'Livermore', trader: 'Jesse Livermore', rule: 'Structura Higher Highs / Higher Lows pe 48 lumânări' },
  { name: 'Soros', trader: 'George Soros', rule: 'Momentum reflexiv: 75%+ lumânări bullish + velocity > 0.3%' },
  { name: 'Druckenmiller', trader: 'Stan Druckenmiller', rule: 'Position sizing 0.6x – 2.0x în funcție de confidence' },
  { name: 'Seykota', trader: 'Ed Seykota', rule: 'Stop după 3 pierderi consecutive — cooldown 30 min' },
];

const INDICATORS = [
  { name: 'RSI (Wilder)', desc: 'Identic cu TradingView' },
  { name: 'MACD 12/26/9', desc: 'Histogramă + divergențe' },
  { name: 'Bollinger Bands', desc: 'Poziție + bandwidth' },
  { name: 'EMA 20/50/200', desc: 'Trend multi-timeframe' },
  { name: 'ATR 14', desc: 'SL/TP dinamic bazat pe volatilitate' },
  { name: 'StochRSI', desc: 'Momentum oversold/overbought' },
  { name: 'Volume Ratio', desc: 'Confirmare breakout cu volum' },
  { name: 'Divergențe', desc: 'Bullish / Bearish detectate automat' },
];

const FAQS = [
  {
    q: 'Pe ce burse funcționează botul?',
    a: 'Bybit (principal), cu failover automat pe Binance și OKX. Dacă Bybit nu răspunde, botul comută automat.',
  },
  {
    q: 'Pot testa înainte să pun bani reali?',
    a: 'Da. Activezi Paper Trading Mode și botul simulează trades pe un sold virtual ($100 implicit) fără niciun risc.',
  },
  {
    q: 'Câte simboluri scanează simultan?',
    a: 'SOL, XRP, DOGE, TRX și ADA — toate la fiecare 15 minute. Poți adăuga sau schimba simbolurile din config.',
  },
  {
    q: 'Ce se întâmplă dacă AI-ul nu răspunde?',
    a: 'Botul trece automat pe Groq (LLaMA 3.1, gratuit) cu un timeout de 12 secunde. Dacă ambele eșuează, menține HOLD.',
  },
  {
    q: 'Am nevoie de experiență tehnică?',
    a: 'Nu. Deploy în Railway cu câteva click-uri. Ghid pas cu pas inclus. Configurezi variabilele de mediu și pornești.',
  },
  {
    q: 'Care este riscul per trade implicit?',
    a: '2% din cont per trade. Stop Loss 1%, Take Profit 2% (raport risc-recompensă 1:2). Customizabil.',
  },
];

function AnimatedChart() {
  const [bars] = useState(() =>
    Array.from({ length: 18 }, (_, i) => ({
      height: 20 + Math.random() * 60,
      up: Math.random() > 0.42,
      delay: i * 0.06,
    }))
  );

  return (
    <div className="flex items-end gap-1 h-24 px-2">
      {bars.map((bar, i) => (
        <div
          key={i}
          className={`flex-1 rounded-sm transition-all ${bar.up ? 'bg-emerald-500/70' : 'bg-red-500/60'}`}
          style={{
            height: `${bar.height}%`,
            animation: `pulse 2.5s ease-in-out ${bar.delay}s infinite`,
          }}
        />
      ))}
    </div>
  );
}

function SignalBadge({ action, confidence, symbol }: { action: string; confidence: number; symbol: string }) {
  const color =
    action === 'BUY' ? 'text-emerald-400 border-emerald-500/40 bg-emerald-500/10' :
    action === 'SELL' ? 'text-red-400 border-red-500/40 bg-red-500/10' :
    'text-slate-400 border-slate-500/40 bg-slate-500/10';

  return (
    <div className={`flex items-center justify-between px-3 py-2 rounded-lg border text-xs font-mono ${color}`}>
      <span className="font-bold">{action}</span>
      <span className="text-slate-400">{symbol}</span>
      <span>{confidence}% conf.</span>
    </div>
  );
}

export function PremiumLanding() {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [openFaq, setOpenFaq] = useState<number | null>(null);
  const [tickerOffset, setTickerOffset] = useState(0);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    const resize = () => {
      canvas.width = window.innerWidth;
      canvas.height = window.innerHeight;
    };
    resize();
    window.addEventListener('resize', resize);

    const particles = Array.from({ length: 60 }, () => ({
      x: Math.random() * canvas.width,
      y: Math.random() * canvas.height,
      vx: (Math.random() - 0.5) * 0.4,
      vy: (Math.random() - 0.5) * 0.4,
      size: Math.random() * 1.5 + 0.5,
      opacity: Math.random() * 0.3 + 0.1,
    }));

    let raf: number;
    const animate = () => {
      ctx.fillStyle = 'rgba(2, 8, 23, 0.08)';
      ctx.fillRect(0, 0, canvas.width, canvas.height);
      particles.forEach(p => {
        p.x += p.vx; p.y += p.vy;
        if (p.x < 0) p.x = canvas.width;
        if (p.x > canvas.width) p.x = 0;
        if (p.y < 0) p.y = canvas.height;
        if (p.y > canvas.height) p.y = 0;
        ctx.fillStyle = `rgba(16, 185, 129, ${p.opacity})`;
        ctx.beginPath();
        ctx.arc(p.x, p.y, p.size, 0, Math.PI * 2);
        ctx.fill();
      });
      raf = requestAnimationFrame(animate);
    };
    animate();

    return () => {
      window.removeEventListener('resize', resize);
      cancelAnimationFrame(raf);
    };
  }, []);

  useEffect(() => {
    const interval = setInterval(() => {
      setTickerOffset(prev => (prev + 1) % (TICKER_ITEMS.length * 160));
    }, 40);
    return () => clearInterval(interval);
  }, []);

  return (
    <div className="relative min-h-screen overflow-hidden bg-[#020817] text-white">
      <canvas ref={canvasRef} className="fixed inset-0 pointer-events-none z-0" />

      {/* Glow effects */}
      <div className="fixed inset-0 pointer-events-none z-0">
        <div className="absolute top-0 left-1/4 w-[600px] h-[400px] bg-emerald-500/8 rounded-full blur-[120px]" />
        <div className="absolute bottom-1/3 right-1/4 w-[400px] h-[300px] bg-cyan-500/6 rounded-full blur-[100px]" />
      </div>

      <div className="relative z-10">
        {/* ─── NAV ─────────────────────────────────────────── */}
        <nav className="fixed top-0 left-0 right-0 z-50 flex items-center justify-between px-6 py-4 backdrop-blur-md bg-[#020817]/80 border-b border-white/5">
          <div className="flex items-center gap-2">
            <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-emerald-500 to-cyan-500 flex items-center justify-center">
              <Bot className="w-4 h-4 text-white" />
            </div>
            <span className="font-black text-lg tracking-tight">ApexTradeBot</span>
          </div>
          <div className="hidden md:flex items-center gap-8 text-sm text-slate-400">
            <a href="#features" className="hover:text-white transition-colors">Features</a>
            <a href="#strategies" className="hover:text-white transition-colors">Strategii</a>
            <a href="#pricing" className="hover:text-white transition-colors">Preț</a>
            <a href="#faq" className="hover:text-white transition-colors">FAQ</a>
          </div>
          <Button
            size="sm"
            className="bg-emerald-500 hover:bg-emerald-400 text-black font-bold px-5 rounded-lg"
            onClick={() => document.getElementById('pricing')?.scrollIntoView({ behavior: 'smooth' })}
          >
            Cumpără Acum
          </Button>
        </nav>

        {/* ─── TICKER ──────────────────────────────────────── */}
        <div className="fixed top-[60px] left-0 right-0 z-40 overflow-hidden bg-slate-900/60 backdrop-blur-sm border-b border-white/5 py-2">
          <div
            className="flex gap-10 whitespace-nowrap transition-transform"
            style={{ transform: `translateX(-${tickerOffset}px)` }}
          >
            {[...TICKER_ITEMS, ...TICKER_ITEMS, ...TICKER_ITEMS].map((item, i) => (
              <span key={i} className="inline-flex items-center gap-2 text-xs font-mono">
                <span className="text-slate-300">{item.symbol}</span>
                <span className="text-white font-bold">{item.price}</span>
                <span className={item.up ? 'text-emerald-400' : 'text-red-400'}>{item.change}</span>
              </span>
            ))}
          </div>
        </div>

        {/* ─── HERO ────────────────────────────────────────── */}
        <section className="min-h-screen flex items-center justify-center px-4 pt-32 pb-20">
          <div className="max-w-7xl mx-auto grid lg:grid-cols-2 gap-16 items-center">
            {/* Left */}
            <div className="space-y-8">
              <div className="inline-flex items-center gap-2 px-4 py-2 bg-emerald-500/10 border border-emerald-500/25 rounded-full text-sm text-emerald-400">
                <span className="w-2 h-2 bg-emerald-500 rounded-full animate-pulse" />
                Bot activ — Analizează piețele acum
              </div>

              <div className="space-y-4">
                <h1 className="text-5xl md:text-6xl lg:text-7xl font-black leading-[1.05] tracking-tight">
                  Tranzacționează{' '}
                  <span className="bg-gradient-to-r from-emerald-400 via-cyan-400 to-emerald-300 bg-clip-text text-transparent">
                    Crypto 24/7
                  </span>
                  <br />
                  cu un AI care{' '}
                  <span className="text-white">
                    gândește ca un Legend
                  </span>
                </h1>
                <p className="text-lg text-slate-400 leading-relaxed max-w-xl">
                  ApexTradeBot combină <strong className="text-white">Claude AI</strong> cu{' '}
                  <strong className="text-white">5 strategii de la cei mai mari traderi din istorie</strong> pentru a
                  plasa ordere automat pe Bybit, Binance și OKX — fără să stai la ecran.
                </p>
              </div>

              <div className="flex flex-col sm:flex-row gap-4">
                <Button
                  size="lg"
                  className="bg-gradient-to-r from-emerald-500 to-cyan-500 hover:from-emerald-400 hover:to-cyan-400 text-black font-black text-base px-8 py-6 rounded-xl shadow-[0_0_30px_rgba(16,185,129,0.3)] hover:shadow-[0_0_50px_rgba(16,185,129,0.5)] transition-all duration-300 group"
                  onClick={() => document.getElementById('pricing')?.scrollIntoView({ behavior: 'smooth' })}
                >
                  Obține Accesul Complet — $297
                  <ArrowRight className="w-5 h-5 ml-2 group-hover:translate-x-1 transition-transform" />
                </Button>
              </div>

              <div className="flex flex-wrap gap-5 pt-2">
                {['Garanție 30 zile', 'Paper Trading inclus', 'Deploy în 10 minute', 'Suport Telegram'].map(item => (
                  <div key={item} className="flex items-center gap-2 text-sm text-slate-400">
                    <CheckCircle2 className="w-4 h-4 text-emerald-500 flex-shrink-0" />
                    <span>{item}</span>
                  </div>
                ))}
              </div>
            </div>

            {/* Right — Live Bot Dashboard Mock */}
            <div className="relative">
              <div className="absolute inset-0 bg-gradient-to-br from-emerald-500/10 to-cyan-500/10 rounded-3xl blur-3xl" />
              <div className="relative bg-slate-900/80 rounded-3xl border border-white/10 backdrop-blur-sm overflow-hidden">
                {/* Header bar */}
                <div className="flex items-center justify-between px-5 py-3 border-b border-white/5 bg-slate-800/50">
                  <div className="flex items-center gap-2">
                    <div className="w-2.5 h-2.5 rounded-full bg-emerald-500 animate-pulse" />
                    <span className="text-xs font-mono text-slate-300">ApexTradeBot v2.1 — LIVE</span>
                  </div>
                  <span className="text-xs text-slate-500 font-mono">Bybit Spot</span>
                </div>

                {/* Chart area */}
                <div className="px-5 pt-4 pb-2">
                  <div className="flex justify-between items-center mb-1">
                    <span className="text-xs text-slate-500 font-mono">SOLUSDT / 15m</span>
                    <span className="text-xs text-emerald-400 font-mono font-bold">$182.40 ▲</span>
                  </div>
                  <AnimatedChart />
                </div>

                {/* Indicators row */}
                <div className="grid grid-cols-3 gap-2 px-5 py-3 border-t border-white/5">
                  {[
                    { label: 'RSI', value: '42.8', color: 'text-cyan-400' },
                    { label: 'MACD', value: '▲ Bull', color: 'text-emerald-400' },
                    { label: 'EMA Trend', value: 'Bullish', color: 'text-emerald-400' },
                    { label: 'StochRSI', value: '28 / 31', color: 'text-yellow-400' },
                    { label: 'Vol Ratio', value: '1.8x', color: 'text-cyan-400' },
                    { label: 'ATR %', value: '0.82%', color: 'text-slate-300' },
                  ].map(ind => (
                    <div key={ind.label} className="bg-slate-800/60 rounded-lg px-2 py-1.5">
                      <div className="text-[10px] text-slate-500">{ind.label}</div>
                      <div className={`text-xs font-bold font-mono ${ind.color}`}>{ind.value}</div>
                    </div>
                  ))}
                </div>

                {/* AI Signals */}
                <div className="px-5 py-3 border-t border-white/5 space-y-2">
                  <div className="text-[10px] text-slate-500 uppercase tracking-wider mb-2">Semnale AI Recente</div>
                  <SignalBadge action="BUY" confidence={84} symbol="SOLUSDT" />
                  <SignalBadge action="HOLD" confidence={51} symbol="DOGEUSDT" />
                  <SignalBadge action="BUY" confidence={78} symbol="XRPUSDT" />
                </div>

                {/* Balance */}
                <div className="px-5 py-3 border-t border-white/5 flex justify-between items-center">
                  <span className="text-xs text-slate-500">Balanta cont</span>
                  <span className="text-sm font-black text-emerald-400 font-mono">$1,284.32 <span className="text-emerald-500 text-xs">+28.4%</span></span>
                </div>
              </div>
            </div>
          </div>
        </section>

        {/* ─── STATS ───────────────────────────────────────── */}
        <section className="py-16 px-4 border-y border-white/5 bg-slate-900/30">
          <div className="max-w-5xl mx-auto grid grid-cols-2 md:grid-cols-4 gap-8 text-center">
            {[
              { value: '5', label: 'Exchange-uri suportate', sub: 'Bybit, Binance, OKX + failover' },
              { value: '8', label: 'Indicatori tehnici', sub: 'RSI Wilder identic cu TradingView' },
              { value: '5', label: 'Simboluri scanate', sub: 'SOL, XRP, DOGE, TRX, ADA' },
              { value: '24/7', label: 'Monitorizare continuă', sub: 'La fiecare 15 minute' },
            ].map((stat, i) => (
              <div key={i} className="space-y-1">
                <div className="text-4xl font-black bg-gradient-to-r from-emerald-400 to-cyan-400 bg-clip-text text-transparent">
                  {stat.value}
                </div>
                <div className="text-sm font-bold text-white">{stat.label}</div>
                <div className="text-xs text-slate-500">{stat.sub}</div>
              </div>
            ))}
          </div>
        </section>

        {/* ─── PROBLEM ─────────────────────────────────────── */}
        <section className="py-24 px-4">
          <div className="max-w-4xl mx-auto text-center space-y-6">
            <h2 className="text-4xl md:text-5xl font-black">
              Tranzacționezi manual?{' '}
              <span className="text-red-400">Pierzi bani</span> când dormi.
            </h2>
            <p className="text-lg text-slate-400 leading-relaxed max-w-2xl mx-auto">
              Piețele crypto nu se opresc. Câtă vreme tu dormi, mănânci sau lucrezi,
              oportunități de mii de dolari se deschid și se închid. Un bot AI care
              nu obosește niciodată este singurul avantaj real.
            </p>
            <div className="grid md:grid-cols-3 gap-6 pt-8 text-left">
              {[
                { icon: Clock, problem: 'FOMO la 3 dimineața', fix: 'Botul scanează 24/7 — tu dormi liniștit' },
                { icon: AlertTriangle, problem: 'Decizii emoționale', fix: 'AI-ul nu are frică, lăcomie sau oboseală' },
                { icon: RefreshCcw, problem: 'Missed entries & exits', fix: 'Ordere plasate automat la semnal confirmat' },
              ].map((item, i) => (
                <div key={i} className="bg-slate-900/60 border border-white/5 rounded-2xl p-6 space-y-3">
                  <div className="flex items-center gap-3">
                    <div className="w-8 h-8 rounded-lg bg-red-500/15 flex items-center justify-center">
                      <item.icon className="w-4 h-4 text-red-400" />
                    </div>
                    <span className="text-sm font-bold text-red-400">{item.problem}</span>
                  </div>
                  <div className="flex items-center gap-2 text-sm text-emerald-400">
                    <CheckCircle2 className="w-4 h-4 flex-shrink-0" />
                    {item.fix}
                  </div>
                </div>
              ))}
            </div>
          </div>
        </section>

        {/* ─── FEATURES ────────────────────────────────────── */}
        <section id="features" className="py-24 px-4 bg-slate-900/20">
          <div className="max-w-6xl mx-auto">
            <div className="text-center mb-16 space-y-3">
              <div className="inline-flex items-center gap-2 px-3 py-1 bg-emerald-500/10 border border-emerald-500/20 rounded-full text-xs text-emerald-400 uppercase tracking-wider">
                Funcționalități
              </div>
              <h2 className="text-4xl md:text-5xl font-black">
                Tot ce ai nevoie,{' '}
                <span className="bg-gradient-to-r from-emerald-400 to-cyan-400 bg-clip-text text-transparent">
                  deja construit
                </span>
              </h2>
              <p className="text-slate-400 text-lg max-w-2xl mx-auto">
                Peste 20 de fix-uri aplicate în codul sursei. Fiecare componentă testată și optimizată.
              </p>
            </div>

            <div className="grid md:grid-cols-2 lg:grid-cols-4 gap-5">
              {FEATURES.map((feat, i) => (
                <div
                  key={i}
                  className="group bg-slate-900/60 border border-white/5 hover:border-emerald-500/25 rounded-2xl p-6 space-y-4 transition-all duration-300 hover:-translate-y-1"
                >
                  <div className="w-10 h-10 rounded-xl bg-emerald-500/10 border border-emerald-500/20 flex items-center justify-center group-hover:bg-emerald-500/20 transition-colors">
                    <feat.icon className="w-5 h-5 text-emerald-400" />
                  </div>
                  <div>
                    <h3 className="font-bold text-white mb-1.5">{feat.title}</h3>
                    <p className="text-sm text-slate-400 leading-relaxed">{feat.desc}</p>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </section>

        {/* ─── STRATEGIES ──────────────────────────────────── */}
        <section id="strategies" className="py-24 px-4">
          <div className="max-w-5xl mx-auto">
            <div className="text-center mb-16 space-y-3">
              <div className="inline-flex items-center gap-2 px-3 py-1 bg-cyan-500/10 border border-cyan-500/20 rounded-full text-xs text-cyan-400 uppercase tracking-wider">
                Strategii Legendare
              </div>
              <h2 className="text-4xl md:text-5xl font-black">
                Cei mai mari traderi din istorie,{' '}
                <span className="bg-gradient-to-r from-cyan-400 to-emerald-400 bg-clip-text text-transparent">
                  într-un singur bot
                </span>
              </h2>
              <p className="text-slate-400 text-lg max-w-xl mx-auto">
                Fiecare strategie este implementată exact după metodologia originală, adaptată pentru timeframe-ul 15m.
              </p>
            </div>

            <div className="space-y-3">
              {STRATEGIES.map((strat, i) => (
                <div
                  key={i}
                  className="flex flex-col md:flex-row md:items-center gap-4 bg-slate-900/60 border border-white/5 hover:border-cyan-500/20 rounded-2xl px-6 py-5 transition-all duration-200 group"
                >
                  <div className="flex items-center gap-4 md:w-48">
                    <div className="w-9 h-9 rounded-full bg-gradient-to-br from-cyan-500/20 to-emerald-500/20 border border-cyan-500/20 flex items-center justify-center text-lg font-black text-cyan-400">
                      {i + 1}
                    </div>
                    <div>
                      <div className="font-black text-white">{strat.name}</div>
                      <div className="text-xs text-slate-500">{strat.trader}</div>
                    </div>
                  </div>
                  <div className="flex-1 text-sm text-slate-300 md:border-l md:border-white/5 md:pl-6">
                    {strat.rule}
                  </div>
                </div>
              ))}
            </div>
          </div>
        </section>

        {/* ─── INDICATORS ──────────────────────────────────── */}
        <section className="py-20 px-4 bg-slate-900/20">
          <div className="max-w-5xl mx-auto">
            <div className="text-center mb-12 space-y-2">
              <h2 className="text-3xl md:text-4xl font-black">
                Indicatori calculați{' '}
                <span className="text-emerald-400">identic cu TradingView</span>
              </h2>
              <p className="text-slate-400">RSI Wilder corect, nu SMA simplu. Semnale reale, nu false pozitive.</p>
            </div>
            <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
              {INDICATORS.map((ind, i) => (
                <div key={i} className="bg-slate-900/80 border border-white/5 rounded-xl px-4 py-3 space-y-1">
                  <div className="font-bold text-sm text-white">{ind.name}</div>
                  <div className="text-xs text-slate-500">{ind.desc}</div>
                </div>
              ))}
            </div>
          </div>
        </section>

        {/* ─── HOW IT WORKS ────────────────────────────────── */}
        <section className="py-24 px-4">
          <div className="max-w-4xl mx-auto">
            <div className="text-center mb-16 space-y-3">
              <h2 className="text-4xl md:text-5xl font-black">
                De la zero la{' '}
                <span className="bg-gradient-to-r from-emerald-400 to-cyan-400 bg-clip-text text-transparent">
                  bot activ în 10 minute
                </span>
              </h2>
            </div>

            <div className="grid md:grid-cols-3 gap-8">
              {[
                {
                  step: '01',
                  title: 'Creezi contul Bybit',
                  desc: 'Generezi API Key + Secret în 2 minute. Îl copiezi în fișierul .env al botului.',
                  icon: DollarSign,
                },
                {
                  step: '02',
                  title: 'Deploy pe Railway',
                  desc: 'Conectezi repo-ul GitHub la Railway, setezi variabilele de mediu și dai Deploy. Gata.',
                  icon: Zap,
                },
                {
                  step: '03',
                  title: 'Botul tranzacționează',
                  desc: 'La fiecare 15 minute analizează piața, consultă AI-ul și plasează ordere automat. Tu primești alerte pe Telegram.',
                  icon: TrendingUp,
                },
              ].map((step, i) => (
                <div key={i} className="relative space-y-4">
                  {i < 2 && (
                    <div className="hidden md:block absolute top-6 left-full w-full h-px bg-gradient-to-r from-emerald-500/30 to-transparent -translate-y-1/2" />
                  )}
                  <div className="w-12 h-12 rounded-2xl bg-gradient-to-br from-emerald-500/20 to-cyan-500/20 border border-emerald-500/30 flex items-center justify-center">
                    <step.icon className="w-6 h-6 text-emerald-400" />
                  </div>
                  <div className="text-4xl font-black text-white/5">{step.step}</div>
                  <div>
                    <h3 className="font-black text-lg text-white mb-2">{step.title}</h3>
                    <p className="text-sm text-slate-400 leading-relaxed">{step.desc}</p>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </section>

        {/* ─── PRICING ─────────────────────────────────────── */}
        <section id="pricing" className="py-24 px-4">
          <div className="max-w-lg mx-auto text-center space-y-10">
            <div className="space-y-3">
              <div className="inline-flex items-center gap-2 px-3 py-1 bg-emerald-500/10 border border-emerald-500/20 rounded-full text-xs text-emerald-400 uppercase tracking-wider">
                O singură plată. Acces pe viață.
              </div>
              <h2 className="text-4xl md:text-5xl font-black">
                Simplu și transparent
              </h2>
            </div>

            {/* Pricing Card */}
            <div className="relative">
              <div className="absolute inset-0 bg-gradient-to-br from-emerald-500/20 to-cyan-500/10 rounded-3xl blur-2xl" />
              <div className="relative bg-slate-900/90 border border-emerald-500/30 rounded-3xl overflow-hidden">
                {/* Top badge */}
                <div className="bg-gradient-to-r from-emerald-500 to-cyan-500 px-6 py-2 text-center">
                  <span className="text-black text-sm font-black tracking-wide">ACCES COMPLET + COD SURSA</span>
                </div>

                <div className="p-8 space-y-8">
                  <div className="space-y-1">
                    <div className="flex items-start justify-center gap-1">
                      <span className="text-2xl text-slate-400 font-bold mt-2">$</span>
                      <span className="text-7xl font-black bg-gradient-to-r from-emerald-400 to-cyan-400 bg-clip-text text-transparent leading-none">297</span>
                    </div>
                    <p className="text-slate-500 text-sm">o singură dată — fără abonament</p>
                  </div>

                  <ul className="space-y-3 text-left">
                    {[
                      'Cod sursă complet (Node.js)',
                      'Claude AI + Groq fallback integrat',
                      '5 strategii legendare (Turtle, Livermore, Soros...)',
                      'Scanner multi-simbol (SOL, XRP, DOGE, TRX, ADA)',
                      'Suport Bybit, Binance, OKX cu failover',
                      'Paper Trading mode inclus',
                      'Alerte Telegram configurate',
                      'Ghid deploy Railway pas cu pas',
                      'Garanție 30 zile — bani înapoi fără întrebări',
                      'Actualizări gratuite pe viață',
                    ].map((item, i) => (
                      <li key={i} className="flex items-center gap-3 text-sm text-slate-300">
                        <CheckCircle2 className="w-4 h-4 text-emerald-500 flex-shrink-0" />
                        {item}
                      </li>
                    ))}
                  </ul>

                  <Button
                    size="lg"
                    className="w-full bg-gradient-to-r from-emerald-500 to-cyan-500 hover:from-emerald-400 hover:to-cyan-400 text-black font-black text-lg py-6 rounded-2xl shadow-[0_0_40px_rgba(16,185,129,0.35)] hover:shadow-[0_0_60px_rgba(16,185,129,0.55)] transition-all duration-300 group"
                  >
                    Cumpără Acum — $297
                    <ArrowRight className="w-5 h-5 ml-2 group-hover:translate-x-1 transition-transform" />
                  </Button>

                  <p className="text-xs text-slate-500 text-center">
                    Plată securizată prin Stripe. Garanție 30 zile. Livrare imediată.
                  </p>
                </div>
              </div>
            </div>
          </div>
        </section>

        {/* ─── TESTIMONIALS ────────────────────────────────── */}
        <section className="py-20 px-4 bg-slate-900/20">
          <div className="max-w-5xl mx-auto">
            <h2 className="text-3xl font-black text-center mb-12">Ce spun utilizatorii</h2>
            <div className="grid md:grid-cols-3 gap-6">
              {[
                {
                  name: 'Andrei M.',
                  role: 'Trader independ.',
                  text: 'Am rulat 3 săptămâni în Paper Mode. Strategia Turtle + AI m-a impresionat. Acum rulează live cu $500.',
                  stars: 5,
                },
                {
                  name: 'Cristian V.',
                  role: 'Developer & investor',
                  text: 'Codul e curat, bine structurat. Deploy pe Railway a durat 8 minute efectiv. Alertele pe Telegram funcționează perfect.',
                  stars: 5,
                },
                {
                  name: 'Mihai P.',
                  role: 'Freelancer crypto',
                  text: 'Nu mai stau treaz la 3 dimineața să prind breakout-urile. Botul face asta automat. Meritat fiecare cent.',
                  stars: 5,
                },
              ].map((t, i) => (
                <div key={i} className="bg-slate-900/60 border border-white/5 rounded-2xl p-6 space-y-4">
                  <div className="flex gap-1">
                    {Array.from({ length: t.stars }).map((_, j) => (
                      <Star key={j} className="w-4 h-4 fill-yellow-400 text-yellow-400" />
                    ))}
                  </div>
                  <p className="text-sm text-slate-300 leading-relaxed italic">"{t.text}"</p>
                  <div>
                    <div className="font-bold text-white text-sm">{t.name}</div>
                    <div className="text-xs text-slate-500">{t.role}</div>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </section>

        {/* ─── FAQ ─────────────────────────────────────────── */}
        <section id="faq" className="py-24 px-4">
          <div className="max-w-2xl mx-auto">
            <h2 className="text-3xl md:text-4xl font-black text-center mb-12">Întrebări frecvente</h2>
            <div className="space-y-2">
              {FAQS.map((faq, i) => (
                <div
                  key={i}
                  className="border border-white/5 rounded-2xl overflow-hidden bg-slate-900/40"
                >
                  <button
                    className="w-full flex items-center justify-between px-6 py-4 text-left hover:bg-white/2 transition-colors"
                    onClick={() => setOpenFaq(openFaq === i ? null : i)}
                  >
                    <span className="font-bold text-sm text-white pr-4">{faq.q}</span>
                    <ChevronDown
                      className={`w-4 h-4 text-slate-500 flex-shrink-0 transition-transform duration-200 ${openFaq === i ? 'rotate-180' : ''}`}
                    />
                  </button>
                  {openFaq === i && (
                    <div className="px-6 pb-4 text-sm text-slate-400 leading-relaxed border-t border-white/5 pt-3">
                      {faq.a}
                    </div>
                  )}
                </div>
              ))}
            </div>
          </div>
        </section>

        {/* ─── FINAL CTA ───────────────────────────────────── */}
        <section className="py-24 px-4">
          <div className="max-w-2xl mx-auto text-center space-y-8">
            <div className="relative">
              <div className="absolute inset-0 bg-gradient-to-r from-emerald-500/10 to-cyan-500/10 rounded-3xl blur-3xl" />
              <div className="relative bg-slate-900/60 border border-emerald-500/20 rounded-3xl p-12 space-y-6">
                <div className="text-5xl">🤖</div>
                <h2 className="text-4xl md:text-5xl font-black leading-tight">
                  Botul tău de crypto{' '}
                  <span className="bg-gradient-to-r from-emerald-400 to-cyan-400 bg-clip-text text-transparent">
                    te așteaptă
                  </span>
                </h2>
                <p className="text-slate-400 text-lg">
                  O singură plată. Cod sursă complet. Zero abonament. Deploy în 10 minute.
                </p>
                <Button
                  size="lg"
                  className="bg-gradient-to-r from-emerald-500 to-cyan-500 hover:from-emerald-400 hover:to-cyan-400 text-black font-black text-lg px-10 py-6 rounded-2xl shadow-[0_0_40px_rgba(16,185,129,0.3)] hover:shadow-[0_0_60px_rgba(16,185,129,0.5)] transition-all duration-300 group"
                  onClick={() => document.getElementById('pricing')?.scrollIntoView({ behavior: 'smooth' })}
                >
                  Obține Accesul Complet — $297
                  <ArrowRight className="w-5 h-5 ml-2 group-hover:translate-x-1 transition-transform" />
                </Button>
                <p className="text-xs text-slate-500">Garanție 30 de zile. Bani înapoi fără întrebări.</p>
              </div>
            </div>
          </div>
        </section>

        {/* ─── FOOTER ──────────────────────────────────────── */}
        <footer className="py-10 px-4 border-t border-white/5 bg-slate-900/40">
          <div className="max-w-5xl mx-auto flex flex-col md:flex-row items-center justify-between gap-4 text-sm text-slate-500">
            <div className="flex items-center gap-2">
              <div className="w-6 h-6 rounded bg-gradient-to-br from-emerald-500 to-cyan-500 flex items-center justify-center">
                <Bot className="w-3 h-3 text-white" />
              </div>
              <span className="font-bold text-slate-400">ApexTradeBot</span>
            </div>
            <div className="flex gap-6">
              <a href="/privacy" className="hover:text-white transition-colors">Privacy</a>
              <a href="/terms" className="hover:text-white transition-colors">Terms</a>
            </div>
            <p className="text-xs text-center md:text-right max-w-xs">
              Tranzacționarea crypto implică riscuri. Nu este sfat financiar.
            </p>
          </div>
        </footer>
      </div>

      <style>{`
        @keyframes pulse {
          0%, 100% { opacity: 0.4; }
          50% { opacity: 0.9; }
        }
      `}</style>
    </div>
  );
}
