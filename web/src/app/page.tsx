"use client";

import React, { useState, useEffect } from "react";
import ModernPaymentForm from "@/components/ui/modern-payment-form";
import { NavbarHero } from "@/components/ui/hero-with-video";
import Script from "next/script";
import { X } from "lucide-react";

const BEAMS = [
  { x:"8%",  dur:"14s", delay:"0s"  },
  { x:"22%", dur:"11s", delay:"3s"  },
  { x:"38%", dur:"16s", delay:"1s"  },
  { x:"54%", dur:"12s", delay:"5s"  },
  { x:"68%", dur:"15s", delay:"2s"  },
  { x:"82%", dur:"13s", delay:"4s"  },
  { x:"93%", dur:"10s", delay:"6s"  },
];

function EtherealBeams() {
  return (
    <div aria-hidden className="fixed inset-0 pointer-events-none z-0 overflow-hidden">
      {BEAMS.map((b, i) => (
        <div key={i} className="absolute top-0 bottom-0 w-px"
          style={{
            left: b.x,
            background: "linear-gradient(to bottom,transparent 0%,rgba(255,255,255,.04) 40%,rgba(255,255,255,.02) 60%,transparent 100%)",
            animation: `beam-fade ${b.dur} ease-in-out ${b.delay} infinite`,
            ["--beam-r" as string]: "0deg",
          }} />
      ))}
    </div>
  );
}

function PaymentModal({ open, onClose }: { open: boolean; onClose: () => void }) {
  useEffect(() => {
    document.body.style.overflow = open ? "hidden" : "";
    return () => { document.body.style.overflow = ""; };
  }, [open]);
  if (!open) return null;
  return (
    <div
      className="fixed inset-0 z-[9999] flex items-start justify-center pt-8 pb-4 px-4 overflow-y-auto"
      style={{ background: "rgba(3,5,8,.94)", backdropFilter: "blur(24px)" }}
      onClick={e => { if (e.target === e.currentTarget) onClose(); }}
    >
      <div className="relative w-full max-w-[440px] my-auto">
        <button
          onClick={onClose}
          className="absolute -top-3 -right-3 z-10 w-7 h-7 rounded-lg flex items-center justify-center"
          style={{ background: "rgba(255,255,255,.06)", border: "1px solid rgba(255,255,255,.1)" }}
        >
          <X className="w-4 h-4 text-white/50" />
        </button>
        <ModernPaymentForm onClose={onClose} />
      </div>
    </div>
  );
}

function DashboardMockup() {
  const [pnl, setPnl] = useState("24.18");
  useEffect(() => {
    const id = setInterval(() => setPnl(v => (parseFloat(v) + Math.random() * .06 - .01).toFixed(2)), 3000);
    return () => clearInterval(id);
  }, []);
  return (
    <div className="flex justify-center px-4 pb-20">
      <div
        className="w-full max-w-[520px] rounded-[18px] overflow-hidden"
        style={{
          border: "1px solid rgba(255,255,255,.1)",
          background: "rgba(6,9,16,.97)",
          boxShadow: "0 40px 80px rgba(0,0,0,.6)",
        }}
      >
        {/* Title bar */}
        <div className="flex items-center justify-between px-4 py-3" style={{ borderBottom: "1px solid rgba(255,255,255,.06)", background: "rgba(255,255,255,.02)" }}>
          <div className="flex gap-[5px]">
            <div className="w-[9px] h-[9px] rounded-full bg-[#ff5f57]" />
            <div className="w-[9px] h-[9px] rounded-full bg-[#febc2e]" />
            <div className="w-[9px] h-[9px] rounded-full bg-[#28c840]" />
          </div>
          <span className="text-[10px] font-mono" style={{ color: "rgba(255,255,255,.25)" }}>APEX · Binance</span>
          <span className="text-[10px] font-mono" style={{ color: "rgba(255,255,255,.25)" }}>RUNNING</span>
        </div>
        <div className="p-5">
          <div className="text-[9px] font-mono tracking-[1.5px] uppercase mb-1" style={{ color: "rgba(255,255,255,.25)" }}>Portfolio Value</div>
          <div className="text-[30px] font-black tracking-[-1px] leading-none mb-1">$1,284.50</div>
          <div className="inline-flex items-center gap-1 text-[11px] font-semibold rounded-[5px] px-2 py-0.5 mb-4" style={{ color: "#10b981", background: "rgba(16,185,129,.08)", border: "1px solid rgba(16,185,129,.15)" }}>
            ▲ +28.4% this month
          </div>
          <div className="relative h-[46px] mb-4">
            <svg viewBox="0 0 560 50" preserveAspectRatio="none" className="absolute inset-0 w-full h-full">
              <defs>
                <linearGradient id="cg" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor="#10b981" stopOpacity=".15" />
                  <stop offset="100%" stopColor="#10b981" stopOpacity="0" />
                </linearGradient>
              </defs>
              <path d="M0,42 C30,40 55,37 80,40 C110,36 140,30 170,24 C200,19 230,15 260,12 C290,9 320,12 350,8 C380,4 410,6 440,3 C470,1 510,3 540,2" fill="none" stroke="#10b981" strokeWidth="1.5" strokeLinecap="round" />
              <path d="M0,42 C30,40 55,37 80,40 C110,36 140,30 170,24 C200,19 230,15 260,12 C290,9 320,12 350,8 C380,4 410,6 440,3 C470,1 510,3 540,2 L540,50 L0,50 Z" fill="url(#cg)" />
            </svg>
          </div>
          <div className="h-px mb-4" style={{ background: "rgba(255,255,255,.06)" }} />
          <div className="flex flex-col gap-2 mb-4">
            {[{ pair: "XRP/USDT", pnl: `+$${pnl}`, price: "@ $2.384" }, { pair: "DOGE/USDT", pnl: "+$11.44", price: "@ $0.182" }].map(r => (
              <div key={r.pair} className="flex items-center justify-between rounded-[9px] px-3 py-2" style={{ background: "rgba(255,255,255,.025)", border: "1px solid rgba(255,255,255,.06)" }}>
                <div className="flex items-center gap-2">
                  <span className="text-[12px] font-bold font-mono">{r.pair}</span>
                  <span className="text-[8px] font-extrabold px-1.5 py-0.5 rounded-[3px]" style={{ color: "#10b981", background: "rgba(16,185,129,.1)", border: "1px solid rgba(16,185,129,.18)" }}>LONG</span>
                </div>
                <div className="text-right">
                  <div className="text-[12px] font-bold font-mono" style={{ color: "#10b981" }}>{r.pnl}</div>
                  <div className="text-[10px] font-mono" style={{ color: "rgba(255,255,255,.25)" }}>{r.price}</div>
                </div>
              </div>
            ))}
          </div>
          <div className="grid grid-cols-3 gap-2">
            {[{ l: "Win Rate", v: "68%", hi: true }, { l: "Trades", v: "847", hi: false }, { l: "Uptime", v: "24/7", hi: false }].map(s => (
              <div key={s.l} className="rounded-[9px] p-2.5" style={{ background: "rgba(255,255,255,.025)", border: "1px solid rgba(255,255,255,.06)" }}>
                <div className="text-[8px] font-mono tracking-[1px] uppercase mb-1" style={{ color: "rgba(255,255,255,.25)" }}>{s.l}</div>
                <div className="text-[16px] font-extrabold leading-none" style={{ color: s.hi ? "#f59e0b" : "#fff" }}>{s.v}</div>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}

const FEATURES = [
  { icon: "⌨", title: "Full Source Code (Node.js)", desc: "Every line, every file — yours to read, modify, and deploy" },
  { icon: "⚡", title: "AI Signal Engine", desc: "Groq LLM + Claude as fallback — free tier covers all signals" },
  { icon: "$", title: "8 Coins — XRP, DOGE, ADA, BTC & more", desc: "Switch pairs with a single env variable change" },
  { icon: "📈", title: "3 Legendary Strategies", desc: "Turtle, Livermore, and Soros — battle-tested frameworks" },
  { icon: "◻", title: "Live TradingView Dashboard", desc: "Real-time P&L, open positions, strategy signals" },
  { icon: "✉", title: "Telegram Alerts", desc: "Instant trade notifications — entry, exit, P&L — every time" },
  { icon: "→", title: "1-Click Railway Deploy", desc: "Paste your API keys, click deploy — live in under 60 seconds" },
  { icon: "⏸", title: "Paper Trading Mode", desc: "Test your strategy with zero real money — before going live" },
];

const FAQS = [
  { q: "Do I need coding experience?", a: "No. You copy-paste your Binance API keys into Railway's environment variables and click deploy. The setup guide walks through every step." },
  { q: "What exchange does it use?", a: "Binance. Available worldwide. Always start with PAPER_TRADING=true before going live." },
  { q: "Can I lose money?", a: "Yes. Always start with PAPER_TRADING=true. Crypto trading carries real financial risk. No strategy wins 100% of the time." },
  { q: "What AI does it use?", a: "The primary engine is Groq — generous free tier. Claude (Anthropic) is used as a fallback for deeper analysis." },
  { q: "Can I change the strategy?", a: "Yes. Every setting — coin, strategy, risk %, stop-loss, take-profit — is an env variable. Switch strategies in seconds." },
];

function SectionLabel({ text }: { text: string }) {
  return (
    <div className="text-[10px] font-semibold uppercase tracking-[3px] mb-4" style={{ color: "rgba(255,255,255,.3)" }}>
      {text}
    </div>
  );
}

export default function Home() {
  const [modalOpen, setModalOpen] = useState(false);
  const [openFaq, setOpenFaq] = useState<number | null>(null);

  return (
    <>
      <Script src="https://js.stripe.com/v3/" strategy="lazyOnload" />
      <EtherealBeams />
      <PaymentModal open={modalOpen} onClose={() => setModalOpen(false)} />

      <div className="relative z-[2]">
        <NavbarHero onGetAccess={() => setModalOpen(true)} />

        <DashboardMockup />

        {/* Ticker */}
        <div className="overflow-hidden py-3" style={{ borderTop: "1px solid rgba(255,255,255,.06)", borderBottom: "1px solid rgba(255,255,255,.06)" }}>
          <div className="flex gap-12 w-max" style={{ animation: "ticker 35s linear infinite" }}>
            {[...Array(2)].map((_, i) => (
              <div key={i} className="flex gap-12 items-center whitespace-nowrap" aria-hidden={i > 0}>
                {["500+ Bots Deployed", "Full Source Code", "XRP · DOGE · ADA · BTC · ETH", "Paper Trading Included", "12+ Countries", "6 Strategies", "Groq AI Engine", "60-Second Deploy", "$0/mo Running Cost"].map(t => (
                  <span key={t} className="flex items-center gap-2 text-[11px]" style={{ color: "rgba(255,255,255,.2)" }}>
                    <span className="w-1 h-1 rounded-full shrink-0" style={{ background: "rgba(255,255,255,.2)" }} />
                    {t}
                  </span>
                ))}
              </div>
            ))}
          </div>
        </div>

        {/* How It Works */}
        <section id="how" className="py-24 px-6" style={{ borderTop: "1px solid rgba(255,255,255,.06)" }}>
          <div className="max-w-[1080px] mx-auto">
            <SectionLabel text="How It Works" />
            <h2 className="font-extrabold tracking-[-1.5px] leading-[1.1] mb-3 max-w-[480px]" style={{ fontSize: "clamp(24px,2.6vw,40px)" }}>
              Three steps to a live bot.
            </h2>
            <p className="text-[14px] max-w-[440px] leading-[1.8] mb-12" style={{ color: "rgba(255,255,255,.4)" }}>
              No trading experience needed. No monthly fees. You own the code forever.
            </p>
            <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
              {[
                { n: "01", t: "Buy Once", d: "Pay $297 once. Get your license key by email instantly. No subscription, no lock-in — ever." },
                { n: "02", t: "Configure", d: "Set your coin, strategy, and risk level in Railway's env variables. No coding needed." },
                { n: "03", t: "Deploy & Earn", d: "One-click deploy on Railway. Live in 60 seconds. Trades 24/7, runs while you sleep." },
              ].map(s => (
                <div key={s.n} className="rounded-[14px] p-7" style={{ background: "rgba(255,255,255,.025)", border: "1px solid rgba(255,255,255,.07)" }}>
                  <div className="font-black leading-none tracking-[-3px] mb-5 tabular-nums" style={{ fontSize: "52px", color: "rgba(255,255,255,.07)" }}>{s.n}</div>
                  <div className="text-[15px] font-semibold mb-2">{s.t}</div>
                  <div className="text-[13px] leading-[1.8]" style={{ color: "rgba(255,255,255,.4)" }}>{s.d}</div>
                </div>
              ))}
            </div>
          </div>
        </section>

        {/* Features */}
        <section id="features" className="py-24 px-6" style={{ borderTop: "1px solid rgba(255,255,255,.06)" }}>
          <div className="max-w-[1080px] mx-auto">
            <SectionLabel text="What's Included" />
            <h2 className="font-extrabold tracking-[-1.5px] mb-3" style={{ fontSize: "clamp(24px,2.6vw,40px)" }}>
              Everything you need for $297.
            </h2>
            <p className="text-[14px] max-w-[440px] leading-[1.8] mb-12" style={{ color: "rgba(255,255,255,.4)" }}>
              Full source code, zero black box. Deploy it, modify it, own it forever.
            </p>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              {FEATURES.map(f => (
                <div key={f.title} className="rounded-[12px] p-5 flex gap-4" style={{ background: "rgba(255,255,255,.025)", border: "1px solid rgba(255,255,255,.07)" }}>
                  <div className="w-8 h-8 rounded-[8px] flex items-center justify-center shrink-0 text-[14px]" style={{ background: "rgba(255,255,255,.05)", border: "1px solid rgba(255,255,255,.08)", color: "rgba(255,255,255,.5)" }}>
                    {f.icon}
                  </div>
                  <div>
                    <div className="text-[13px] font-semibold mb-0.5">{f.title}</div>
                    <div className="text-[11px] leading-[1.7]" style={{ color: "rgba(255,255,255,.35)" }}>{f.desc}</div>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </section>

        {/* Reviews */}
        <section className="py-24 px-6" style={{ borderTop: "1px solid rgba(255,255,255,.06)" }}>
          <div className="max-w-[1080px] mx-auto">
            <SectionLabel text="Traders" />
            <h2 className="font-extrabold tracking-[-1.5px] mb-12" style={{ fontSize: "clamp(24px,2.6vw,40px)" }}>
              Real people, real profits.
            </h2>
            <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
              {[
                { text: '"Deployed in 8 minutes. First trade was live by morning. I\'ve tried $50/month SaaS bots and this destroys all of them."', author: "Marco V. · Netherlands" },
                { text: '"Win rate has been ~64% over 3 weeks live. Starting in paper mode first was the right call. Genuinely impressed."', author: "James K. · United Kingdom" },
                { text: '"Tried 4 bots before this. Only one where I own the code outright. Nobody can shut it down or change the terms on me."', author: "David L. · Canada" },
              ].map(r => (
                <div key={r.author} className="rounded-[14px] p-6" style={{ background: "rgba(255,255,255,.025)", border: "1px solid rgba(255,255,255,.07)" }}>
                  <div className="text-[11px] tracking-[3px] mb-3" style={{ color: "rgba(255,255,255,.5)" }}>★★★★★</div>
                  <p className="text-[13px] leading-[1.85] mb-4" style={{ color: "rgba(255,255,255,.5)" }}>{r.text}</p>
                  <div className="text-[10px] font-semibold uppercase tracking-[.5px]" style={{ color: "rgba(255,255,255,.25)" }}>{r.author}</div>
                </div>
              ))}
            </div>
          </div>
        </section>

        {/* Pricing */}
        <section id="pricing" className="py-24 px-6 text-center" style={{ borderTop: "1px solid rgba(255,255,255,.06)" }}>
          <div className="max-w-[1080px] mx-auto">
            <SectionLabel text="Pricing" />
            <h2 className="font-extrabold tracking-[-1.5px] mb-3" style={{ fontSize: "clamp(24px,2.6vw,40px)" }}>
              One payment. Yours forever.
            </h2>
            <p className="text-[14px] max-w-[440px] mx-auto leading-[1.8] mb-12" style={{ color: "rgba(255,255,255,.4)" }}>
              No monthly fees. No SaaS trap. The source code is yours permanently.
            </p>
            <div className="max-w-[420px] mx-auto rounded-[18px] overflow-hidden" style={{ background: "rgba(255,255,255,.025)", border: "1px solid rgba(255,255,255,.1)" }}>
              <div className="px-8 pt-7 pb-6" style={{ borderBottom: "1px solid rgba(255,255,255,.07)" }}>
                <div className="text-[9px] font-bold uppercase tracking-[3px] mb-4" style={{ color: "rgba(255,255,255,.3)" }}>
                  One-Time Access
                </div>
                <div className="flex items-baseline justify-center gap-3 mb-2">
                  <span className="font-black tracking-[-4px] leading-none" style={{ fontSize: "68px" }}>$297</span>
                  <span className="text-[20px] line-through font-normal" style={{ color: "rgba(255,255,255,.2)" }}>$497</span>
                </div>
                <div className="text-[11px]" style={{ color: "rgba(255,255,255,.2)" }}>one-time · no subscription · lifetime access</div>
              </div>
              <div className="p-7">
                <ul className="space-y-3 mb-7 text-left">
                  {[
                    "Full source code (Node.js) — you own it forever",
                    "AI signal engine — Groq + Claude (free to run)",
                    "8 coins — XRP, DOGE, ADA, BTC, ETH, SOL, BNB, TRX",
                    "3 legendary strategies — Turtle, Livermore, Soros",
                    "Live TradingView dashboard + Telegram alerts",
                    "1-click Railway deploy + paper trading mode",
                  ].map(item => (
                    <li key={item} className="flex gap-2.5 items-start text-[13px]" style={{ color: "rgba(255,255,255,.5)" }}>
                      <svg className="w-3.5 h-3.5 shrink-0 mt-0.5" fill="none" stroke="rgba(255,255,255,.4)" strokeWidth="2.5" viewBox="0 0 24 24">
                        <polyline points="20 6 9 17 4 12" />
                      </svg>
                      {item}
                    </li>
                  ))}
                </ul>
                <button
                  onClick={() => setModalOpen(true)}
                  className="w-full py-4 text-black font-extrabold text-[13px] rounded-[10px] transition-opacity hover:opacity-90"
                  style={{ background: "#f59e0b", boxShadow: "0 0 32px rgba(245,158,11,.2)" }}
                >
                  Get Instant Access — $297 →
                </button>
                <p className="text-center text-[10px] mt-3" style={{ color: "rgba(255,255,255,.2)" }}>
                  Stripe encrypted · Instant delivery · 30-day money back
                </p>
              </div>
            </div>
          </div>
        </section>

        {/* FAQ */}
        <section id="faq" className="py-24 px-6" style={{ borderTop: "1px solid rgba(255,255,255,.06)" }}>
          <div className="max-w-[1080px] mx-auto">
            <SectionLabel text="FAQ" />
            <h2 className="font-extrabold tracking-[-1.5px] mb-10" style={{ fontSize: "clamp(24px,2.6vw,40px)" }}>
              Common questions.
            </h2>
            <div className="max-w-[620px]" style={{ borderTop: "1px solid rgba(255,255,255,.07)" }}>
              {FAQS.map((f, i) => (
                <div key={i} style={{ borderBottom: "1px solid rgba(255,255,255,.07)" }}>
                  <button
                    className="w-full flex items-center justify-between py-5 text-left text-[14px] gap-4"
                    style={{ color: openFaq === i ? "#fff" : "rgba(255,255,255,.5)" }}
                    onClick={() => setOpenFaq(openFaq === i ? null : i)}
                  >
                    {f.q}
                    <span
                      className="w-5 h-5 rounded-[5px] flex items-center justify-center text-[14px] shrink-0 transition-transform"
                      style={{
                        background: "rgba(255,255,255,.06)",
                        border: "1px solid rgba(255,255,255,.08)",
                        color: "rgba(255,255,255,.4)",
                        transform: openFaq === i ? "rotate(45deg)" : "none",
                      }}
                    >+</span>
                  </button>
                  {openFaq === i && (
                    <div className="pb-5 text-[13px] leading-[1.9]" style={{ color: "rgba(255,255,255,.45)" }}>{f.a}</div>
                  )}
                </div>
              ))}
            </div>
          </div>
        </section>

        {/* Footer */}
        <footer style={{ borderTop: "1px solid rgba(255,255,255,.07)" }}>
          <div className="max-w-[1080px] mx-auto px-6 py-6 flex flex-wrap items-center justify-between gap-3">
            <a href="#" className="flex items-center gap-2 text-[13px] font-bold no-underline" style={{ color: "rgba(255,255,255,.4)" }}>
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                <polyline points="22 7 13.5 15.5 8.5 10.5 2 17" /><polyline points="16 7 22 7 22 13" />
              </svg>
              Apex Trade Bot
            </a>
            <div className="flex gap-5">
              {[["Privacy", "/privacy"], ["Terms", "/terms"], ["Support", "mailto:support@aicashsystem.space"]].map(([l, h]) => (
                <a key={l} href={h} className="text-[11px] no-underline" style={{ color: "rgba(255,255,255,.2)" }}>{l}</a>
              ))}
            </div>
            <div className="text-[11px]" style={{ color: "rgba(255,255,255,.2)" }}>© 2025 AICashSystem</div>
          </div>
          <div className="max-w-[1080px] mx-auto px-6 pb-6 text-center text-[10px] leading-[1.7]" style={{ color: "rgba(255,255,255,.12)" }}>
            Apex Trade Bot is automation software sold as source code. Not financial advice. Crypto trading involves substantial risk of loss. Always use paper trading mode before trading with real capital.
          </div>
        </footer>
      </div>
    </>
  );
}
