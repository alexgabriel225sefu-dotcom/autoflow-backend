"use client";

import React, { useState, useEffect } from "react";
import { Button } from "@/components/ui/button";
import ModernPaymentForm from "@/components/ui/modern-payment-form";
import Script from "next/script";
import { Shield, Clock, Code2, BrainCircuit, DollarSign, Activity, Send, Package, ShieldCheck, X, Zap } from "lucide-react";

const BEAMS = [
  { x:"5%",  dur:"12s", delay:"0s",   r:"30deg" },
  { x:"12%", dur:"9s",  delay:"2s",   r:"32deg" },
  { x:"20%", dur:"14s", delay:".5s",  r:"28deg" },
  { x:"29%", dur:"11s", delay:"3.5s", r:"33deg" },
  { x:"38%", dur:"10s", delay:"1.5s", r:"29deg" },
  { x:"47%", dur:"13s", delay:"4s",   r:"31deg" },
  { x:"55%", dur:"8s",  delay:".8s",  r:"34deg" },
  { x:"63%", dur:"15s", delay:"2.5s", r:"27deg" },
  { x:"72%", dur:"11s", delay:"5s",   r:"32deg" },
  { x:"80%", dur:"9s",  delay:"1s",   r:"30deg" },
  { x:"88%", dur:"13s", delay:"3s",   r:"28deg" },
  { x:"95%", dur:"10s", delay:"6s",   r:"35deg" },
];

function EtherealBeams() {
  return (
    <div aria-hidden className="fixed inset-0 pointer-events-none z-0 overflow-hidden">
      {BEAMS.map((b, i) => (
        <div key={i} className="absolute top-0 bottom-0 w-px"
          style={{ left:b.x, background:"linear-gradient(to bottom,transparent 0%,rgba(245,158,11,.42) 40%,rgba(251,191,36,.18) 60%,transparent 100%)", filter:"blur(.5px)", animation:`beam-fade ${b.dur} ease-in-out ${b.delay} infinite`, ["--beam-r" as string]:b.r }} />
      ))}
    </div>
  );
}

function AmbientGlow() {
  return (
    <div aria-hidden className="fixed inset-0 pointer-events-none z-0 overflow-hidden">
      <div className="absolute w-[700px] h-[700px] rounded-full opacity-[.12] blur-[130px] -top-64 -left-32" style={{background:"#92400e"}} />
      <div className="absolute w-[500px] h-[500px] rounded-full opacity-[.10] blur-[130px] -bottom-48 -right-20" style={{background:"#78350f"}} />
    </div>
  );
}

function PaymentModal({ open, onClose }: { open:boolean; onClose:()=>void }) {
  useEffect(() => { document.body.style.overflow = open ? "hidden" : ""; return () => { document.body.style.overflow = ""; }; }, [open]);
  if (!open) return null;
  return (
    <div className="fixed inset-0 z-[9999] flex items-start justify-center pt-8 pb-4 px-4 overflow-y-auto" style={{background:"rgba(3,5,8,.92)",backdropFilter:"blur(28px)"}} onClick={e=>{if(e.target===e.currentTarget)onClose()}}>
      <div className="relative w-full max-w-[440px] my-auto">
        <button onClick={onClose} className="absolute -top-3 -right-3 z-10 w-7 h-7 rounded-lg flex items-center justify-center transition-colors" style={{background:"rgba(255,255,255,.06)",border:"1px solid rgba(255,255,255,.1)"}}>
          <X className="w-4 h-4 text-white/50" />
        </button>
        <ModernPaymentForm onClose={onClose} />
      </div>
    </div>
  );
}

function DashboardMockup() {
  const [pnl, setPnl] = useState("24.18");
  useEffect(() => { const id = setInterval(()=>setPnl(v=>(parseFloat(v)+Math.random()*.06-.01).toFixed(2)),3000); return ()=>clearInterval(id); }, []);
  return (
    <div className="relative flex justify-center px-4 pb-20">
      <div className="relative z-20 w-full max-w-[540px] rounded-[18px] overflow-hidden border" style={{borderColor:"rgba(255,255,255,.11)",background:"rgba(6,9,16,.97)",boxShadow:"0 40px 100px rgba(0,0,0,.7),0 0 0 1px rgba(245,158,11,.06)"}}>
        <div className="flex items-center justify-between px-4 py-3 border-b" style={{background:"rgba(255,255,255,.03)",borderColor:"rgba(255,255,255,.07)"}}>
          <div className="flex gap-[5px]">
            <div className="w-[9px] h-[9px] rounded-full bg-[#ff5f57]" /><div className="w-[9px] h-[9px] rounded-full bg-[#febc2e]" /><div className="w-[9px] h-[9px] rounded-full bg-[#28c840]" />
          </div>
          <span className="text-[10px] font-mono tracking-[.5px]" style={{color:"rgba(255,255,255,.3)"}}>APEX · Binance</span>
          <span className="text-[10px] font-mono tracking-[.5px]" style={{color:"rgba(255,255,255,.3)"}}>RUNNING</span>
        </div>
        <div className="p-4">
          <div className="text-[9px] font-mono tracking-[1.5px] uppercase mb-1" style={{color:"rgba(255,255,255,.3)"}}>Portfolio Value</div>
          <div className="text-[32px] font-black tracking-[-1.5px] leading-none mb-1">$1,284.50</div>
          <div className="inline-flex items-center gap-1 text-[11px] font-semibold rounded-[5px] px-2 py-0.5 mb-3" style={{color:"#10b981",background:"rgba(16,185,129,.1)",border:"1px solid rgba(16,185,129,.18)"}}>▲ +28.4% this month</div>
          <div className="relative h-[50px] mb-3">
            <svg viewBox="0 0 560 50" preserveAspectRatio="none" className="absolute inset-0 w-full h-full">
              <defs><linearGradient id="cg" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor="#10b981" stopOpacity=".2"/><stop offset="100%" stopColor="#10b981" stopOpacity="0"/></linearGradient></defs>
              <path d="M0,42 C30,40 55,37 80,40 C110,36 140,30 170,24 C200,19 230,15 260,12 C290,9 320,12 350,8 C380,4 410,6 440,3 C470,1 510,3 540,2" fill="none" stroke="#10b981" strokeWidth="1.6" strokeLinecap="round"/>
              <path d="M0,42 C30,40 55,37 80,40 C110,36 140,30 170,24 C200,19 230,15 260,12 C290,9 320,12 350,8 C380,4 410,6 440,3 C470,1 510,3 540,2 L540,50 L0,50 Z" fill="url(#cg)"/>
            </svg>
          </div>
          <div className="h-px mb-3" style={{background:"rgba(255,255,255,.07)"}} />
          <div className="flex flex-col gap-2 mb-3">
            {[{pair:"XRP/USDT",pnl:`+$${pnl}`,price:"@ $2.384"},{pair:"DOGE/USDT",pnl:"+$11.44",price:"@ $0.182"}].map(r=>(
              <div key={r.pair} className="flex items-center justify-between rounded-[9px] px-3 py-2" style={{background:"rgba(255,255,255,.025)",border:"1px solid rgba(255,255,255,.07)"}}>
                <div className="flex items-center gap-2">
                  <span className="text-[12px] font-bold font-mono">{r.pair}</span>
                  <span className="text-[8px] font-extrabold px-1.5 py-0.5 rounded-[3px] tracking-[.5px]" style={{color:"#10b981",background:"rgba(16,185,129,.13)",border:"1px solid rgba(16,185,129,.2)"}}>LONG</span>
                </div>
                <div className="text-right">
                  <div className="text-[12px] font-bold font-mono" style={{color:"#10b981"}}>{r.pnl}</div>
                  <div className="text-[10px] font-mono" style={{color:"rgba(255,255,255,.3)"}}>{r.price}</div>
                </div>
              </div>
            ))}
          </div>
          <div className="grid grid-cols-3 gap-2">
            {[{l:"Win Rate",v:"68%",c:"#f59e0b"},{l:"Trades",v:"847",c:"#fff"},{l:"Uptime",v:"24/7",c:"#10b981"}].map(s=>(
              <div key={s.l} className="rounded-[9px] p-2.5" style={{background:"rgba(255,255,255,.025)",border:"1px solid rgba(255,255,255,.07)"}}>
                <div className="text-[8px] font-mono tracking-[1px] uppercase mb-1" style={{color:"rgba(255,255,255,.3)"}}>{s.l}</div>
                <div className="text-[17px] font-extrabold leading-none" style={{color:s.c}}>{s.v}</div>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}

export default function Home() {
  const [modalOpen, setModalOpen] = useState(false);
  const [openFaq, setOpenFaq] = useState<number|null>(null);

  const features = [
    {icon:<Code2/>,title:"Full Source Code (Node.js)",desc:"Every line, every file — yours to read, modify, and deploy"},
    {icon:<BrainCircuit/>,title:"AI Signal Engine",desc:"Groq LLM + Claude as fallback — free tier covers all signals"},
    {icon:<DollarSign/>,title:"8 Coins — XRP, DOGE, ADA, BTC & more",desc:"Switch pairs with a single env variable change"},
    {icon:<Activity/>,title:"3 Legendary Strategies",desc:"Turtle, Livermore, and Soros — battle-tested frameworks"},
    {icon:<Zap/>,title:"Live TradingView Dashboard",desc:"Real-time P&L, open positions, strategy signals"},
    {icon:<Send/>,title:"Telegram Alerts",desc:"Instant trade notifications — entry, exit, P&L — every time"},
    {icon:<Package/>,title:"1-Click Railway Deploy",desc:"Paste your API keys, click deploy — live in under 60 seconds"},
    {icon:<ShieldCheck/>,title:"Paper Trading Mode",desc:"Test your strategy with zero real money — before going live"},
  ];

  const faqs = [
    {q:"Do I need coding experience?",a:"No. You copy-paste your Binance API keys into Railway's environment variables and click deploy. The setup guide walks through every step."},
    {q:"What exchange does it use?",a:"Binance. Available worldwide. Always start with PAPER_TRADING=true before going live."},
    {q:"Can I lose money?",a:"Yes. Always start with PAPER_TRADING=true. Crypto trading carries real financial risk. No strategy wins 100% of the time."},
    {q:"What AI does it use?",a:"The primary engine is Groq — generous free tier. Claude (Anthropic) is used as a fallback for deeper analysis."},
    {q:"Can I change the strategy?",a:"Yes. Every setting — coin, strategy, risk %, stop-loss, take-profit — is an env variable. Switch strategies in seconds."},
  ];

  return (
    <>
      <Script src="https://js.stripe.com/v3/" strategy="lazyOnload"/>
      <AmbientGlow/>
      <EtherealBeams/>
      <PaymentModal open={modalOpen} onClose={()=>setModalOpen(false)}/>
      <div className="relative z-[2]">
        {/* Nav */}
        <nav className="fixed top-0 left-0 right-0 z-[200] h-[58px] flex items-center justify-between px-7">
          <a href="#" className="flex items-center gap-2 text-[14px] font-bold text-white no-underline">
            <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="#f59e0b" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"><polyline points="22 7 13.5 15.5 8.5 10.5 2 17"/><polyline points="16 7 22 7 22 13"/></svg>
            Apex Trade Bot
          </a>
          <div className="hidden md:flex gap-6">
            {[["How It Works","#how"],["Features","#features"],["Pricing","#pricing"]].map(([l,h])=>(
              <a key={l} href={h} className="text-[13px] no-underline transition-colors" style={{color:"rgba(255,255,255,.3)"}}>{l}</a>
            ))}
          </div>
          <button onClick={()=>setModalOpen(true)} className="px-4 py-2 text-black text-[12px] font-bold rounded-lg transition-colors" style={{background:"#f59e0b"}}>
            Get Access →
          </button>
        </nav>

        {/* Hero */}
        <section className="min-h-screen flex flex-col items-center justify-center text-center px-6 pt-24 pb-16">
          <div className="inline-flex items-center gap-2 px-3 py-1.5 rounded-full text-[11px] font-medium mb-7 cursor-default transition-colors" style={{border:"1px solid rgba(255,255,255,.11)",background:"rgba(255,255,255,.06)",color:"rgba(255,255,255,.35)"}}>
            <strong style={{color:"#f59e0b",fontWeight:600}}>500+ bots deployed</strong>
            <span className="w-px h-2.5" style={{background:"rgba(255,255,255,.15)"}}/>
            Full source code · No subscriptions
          </div>
          <h1 className="font-black leading-[.97] mb-5 max-w-[860px]" style={{fontSize:"clamp(44px,6.5vw,86px)",letterSpacing:"-3.5px"}}>
            The trading bot<br/>
            you <em className="not-italic" style={{background:"linear-gradient(120deg,#fbbf24,#f59e0b 45%,#f97316)",WebkitBackgroundClip:"text",WebkitTextFillColor:"transparent",backgroundClip:"text"}}>actually own.</em>
          </h1>
          <p className="leading-[1.75] max-w-[540px] mb-9 font-light" style={{fontSize:"clamp(15px,1.5vw,18px)",color:"rgba(255,255,255,.5)"}}>
            Others charge $99/month for a bot you don't control. You buy once, get every line of code, and deploy it yourself. No fees. No lock-in. No black box.
          </p>
          <div className="flex gap-2.5 flex-wrap justify-center mb-9">
            <button onClick={()=>setModalOpen(true)} className="inline-flex items-center gap-2 px-7 py-3.5 text-black text-[13px] font-extrabold rounded-[10px] transition-all" style={{background:"#f59e0b",boxShadow:"0 0 40px rgba(245,158,11,.25)"}}>
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"><polyline points="22 7 13.5 15.5 8.5 10.5 2 17"/></svg>
              Get the Bot — $297
            </button>
            <a href="#how" className="inline-flex items-center gap-2 px-6 py-3.5 text-[13px] rounded-[10px] transition-all no-underline" style={{border:"1px solid rgba(255,255,255,.11)",color:"rgba(255,255,255,.6)"}}>
              See How It Works
            </a>
          </div>
          <div className="flex items-center gap-5 flex-wrap justify-center">
            {[{i:<Shield className="w-3 h-3"/>,t:"Stripe Encrypted"},{i:<svg className="w-3 h-3" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><polyline points="20 6 9 17 4 12"/></svg>,t:"Instant Delivery"},{i:<Clock className="w-3 h-3"/>,t:"No Monthly Fees"}].map(x=>(
              <span key={x.t} className="flex items-center gap-1.5 text-[11px] font-medium" style={{color:"rgba(255,255,255,.3)"}}><span style={{color:"#f59e0b"}}>{x.i}</span>{x.t}</span>
            ))}
          </div>
        </section>

        <DashboardMockup/>

        {/* Ticker */}
        <div className="overflow-hidden py-3" style={{borderTop:"1px solid rgba(255,255,255,.07)",borderBottom:"1px solid rgba(255,255,255,.07)",background:"rgba(255,255,255,.01)"}}>
          <div className="flex gap-12 w-max" style={{animation:"ticker 35s linear infinite"}}>
            {[...Array(2)].map((_,i)=>(
              <div key={i} className="flex gap-12 items-center whitespace-nowrap" aria-hidden={i>0}>
                {["500+ Bots Deployed","Full Source Code — You Own It","XRP · DOGE · ADA · BTC · ETH","Paper Trading Mode Included","12+ Countries","6 Legendary Strategies","Groq AI Engine","Railway Deploy — 60 Seconds","$0/mo Running Cost"].map(t=>(
                  <span key={t} className="flex items-center gap-2 text-[11px] font-medium" style={{color:"rgba(255,255,255,.3)"}}>
                    <span className="w-1 h-1 rounded-full shrink-0" style={{background:"rgba(245,158,11,.4)"}}/>
                    {t}
                  </span>
                ))}
              </div>
            ))}
          </div>
        </div>

        {/* How It Works */}
        <section id="how" className="py-24 px-7" style={{background:"linear-gradient(180deg,#03050c,#06080f 50%,#03050c)"}}>
          <div className="max-w-[1100px] mx-auto">
            <div className="flex items-center gap-2 text-[10px] font-bold uppercase tracking-[3px] mb-3.5" style={{color:"#f59e0b"}}><span className="w-5 h-px" style={{background:"#f59e0b"}}/>How It Works</div>
            <h2 className="font-extrabold tracking-[-1.5px] leading-[1.1] mb-3" style={{fontSize:"clamp(26px,2.8vw,42px)"}}>Three steps to a live bot.</h2>
            <p className="text-[15px] max-w-[480px] leading-[1.8] font-light mb-12" style={{color:"rgba(255,255,255,.5)"}}>No trading experience needed. No monthly fees. You own the code forever.</p>
            <div className="grid grid-cols-1 md:grid-cols-3 gap-px rounded-[14px] overflow-hidden" style={{background:"rgba(255,255,255,.07)",border:"1px solid rgba(255,255,255,.07)"}}>
              {[{n:"01",t:"Buy Once",d:"Pay $297 once. Get your license key by email instantly. No subscription, no lock-in — ever."},{n:"02",t:"Configure",d:"Set your coin, strategy, and risk level in Railway's env variables. No coding needed."},{n:"03",t:"Deploy & Earn",d:"One-click deploy on Railway. Live in 60 seconds. Trades 24/7, runs while you sleep."}].map(s=>(
                <div key={s.n} className="p-8 transition-colors hover:bg-white/[.02]" style={{background:"#03050c"}}>
                  <div className="font-black leading-none tracking-[-3px] mb-5 tabular-nums" style={{fontSize:"56px",color:"rgba(245,158,11,.1)"}}>{s.n}</div>
                  <div className="text-[16px] font-bold mb-2">{s.t}</div>
                  <div className="text-[13px] leading-[1.8]" style={{color:"rgba(255,255,255,.45)"}}>{s.d}</div>
                </div>
              ))}
            </div>
          </div>
        </section>

        {/* Features */}
        <section id="features" className="py-24 px-7" style={{background:"#06080f",borderTop:"1px solid rgba(255,255,255,.07)"}}>
          <div className="max-w-[1100px] mx-auto">
            <div className="flex items-center gap-2 text-[10px] font-bold uppercase tracking-[3px] mb-3.5" style={{color:"#f59e0b"}}><span className="w-5 h-px" style={{background:"#f59e0b"}}/>What's Included</div>
            <h2 className="font-extrabold tracking-[-1.5px] mb-3" style={{fontSize:"clamp(26px,2.8vw,42px)"}}>Everything you need for $297.</h2>
            <p className="text-[15px] max-w-[480px] leading-[1.8] font-light mb-12" style={{color:"rgba(255,255,255,.5)"}}>Full source code, zero black box. Deploy it, modify it, own it forever.</p>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-px rounded-[14px] overflow-hidden" style={{background:"rgba(255,255,255,.07)",border:"1px solid rgba(255,255,255,.07)"}}>
              {features.map(f=>(
                <div key={f.title} className="p-5 flex gap-3.5 transition-colors hover:bg-white/[.02]" style={{background:"#06080f"}}>
                  <div className="w-[34px] h-[34px] rounded-[8px] flex items-center justify-center shrink-0 [&_svg]:w-[15px] [&_svg]:h-[15px] [&_svg]:stroke-[#f59e0b] [&_svg]:fill-none [&_svg]:[stroke-width:2]" style={{background:"rgba(245,158,11,.06)",border:"1px solid rgba(245,158,11,.15)"}}>
                    {f.icon}
                  </div>
                  <div>
                    <div className="text-[13px] font-semibold mb-0.5">{f.title}</div>
                    <div className="text-[11px] leading-[1.6]" style={{color:"rgba(255,255,255,.35)"}}>{f.desc}</div>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </section>

        {/* Reviews */}
        <section id="reviews" className="py-24 px-7">
          <div className="max-w-[1100px] mx-auto">
            <div className="flex items-center gap-2 text-[10px] font-bold uppercase tracking-[3px] mb-3.5" style={{color:"#f59e0b"}}><span className="w-5 h-px" style={{background:"#f59e0b"}}/>Traders</div>
            <h2 className="font-extrabold tracking-[-1.5px] mb-12" style={{fontSize:"clamp(26px,2.8vw,42px)"}}>Real people, real profits.</h2>
            <div className="grid grid-cols-1 md:grid-cols-3 gap-3.5">
              {[{text:'"Deployed in 8 minutes. First trade was live by morning. I\'ve tried $50/month SaaS bots and this destroys all of them."',author:"Marco V. · Netherlands"},{text:'"Win rate has been ~64% over 3 weeks live. Starting in paper mode first was the right call. Genuinely impressed."',author:"James K. · United Kingdom"},{text:'"Tried 4 bots before this. Only one where I own the code outright. Nobody can shut it down or change the terms on me."',author:"David L. · Canada"}].map(r=>(
                <div key={r.author} className="rounded-[14px] p-5 transition-colors" style={{background:"rgba(255,255,255,.025)",border:"1px solid rgba(255,255,255,.07)"}}>
                  <div className="text-[12px] tracking-[2px] mb-3" style={{color:"#f59e0b"}}>★★★★★</div>
                  <p className="text-[13px] leading-[1.85] italic mb-3.5" style={{color:"rgba(255,255,255,.55)"}}>{r.text}</p>
                  <div className="text-[10px] font-bold uppercase tracking-[.5px]" style={{color:"rgba(255,255,255,.3)"}}>{r.author}</div>
                </div>
              ))}
            </div>
          </div>
        </section>

        {/* Pricing */}
        <section id="pricing" className="py-24 px-7 text-center" style={{background:"#06080f",borderTop:"1px solid rgba(255,255,255,.07)"}}>
          <div className="max-w-[1100px] mx-auto">
            <div className="flex items-center justify-center gap-2 text-[10px] font-bold uppercase tracking-[3px] mb-3.5" style={{color:"#f59e0b"}}><span className="w-5 h-px" style={{background:"#f59e0b"}}/>Pricing</div>
            <h2 className="font-extrabold tracking-[-1.5px] mb-3" style={{fontSize:"clamp(26px,2.8vw,42px)"}}>One payment. Yours forever.</h2>
            <p className="text-[15px] max-w-[480px] mx-auto leading-[1.8] font-light mb-12" style={{color:"rgba(255,255,255,.5)"}}>No monthly fees. No SaaS trap. The source code is yours permanently.</p>
            <div className="relative max-w-[440px] mx-auto rounded-[18px]">
              <div className="absolute inset-[-1px] rounded-[19px]" style={{background:"linear-gradient(135deg,rgba(245,158,11,.35),rgba(245,158,11,.08) 50%,rgba(245,158,11,.25)}"}} />
              <div className="relative rounded-[18px] overflow-hidden" style={{background:"#06080f"}}>
                <div className="px-8 pt-7 pb-5" style={{background:"rgba(245,158,11,.03)",borderBottom:"1px solid rgba(245,158,11,.08)"}}>
                  <div className="flex items-center justify-center gap-2 text-[9px] font-extrabold uppercase tracking-[3px] mb-3" style={{color:"#f59e0b"}}>
                    One-Time Access <span className="text-white text-[7px] px-1.5 py-0.5 rounded font-black tracking-[1px]" style={{background:"#dc2626"}}>LIMITED</span>
                  </div>
                  <div className="flex items-baseline justify-center gap-2.5 mb-1.5">
                    <span className="font-black tracking-[-4px] leading-none" style={{fontSize:"72px",background:"linear-gradient(135deg,#fff,rgba(255,255,255,.65))",WebkitBackgroundClip:"text",WebkitTextFillColor:"transparent"}}>$297</span>
                    <span className="text-[22px] line-through font-normal" style={{color:"rgba(255,255,255,.25)"}}>$497</span>
                  </div>
                  <div className="text-[11px] tracking-[1px]" style={{color:"rgba(255,255,255,.25)"}}>one-time · no subscription · lifetime access</div>
                </div>
                <div className="p-7">
                  <ul className="space-y-3 mb-6 text-left">
                    {["Full source code (Node.js) — you own it forever","AI signal engine — Groq + Claude (free to run)","8 coins — XRP, DOGE, ADA, BTC, ETH, SOL, BNB, TRX","3 legendary strategies — Turtle, Livermore, Soros","Live TradingView dashboard + Telegram alerts","1-click Railway deploy + paper trading mode"].map(item=>(
                      <li key={item} className="flex gap-2.5 items-start text-[13px]" style={{color:"rgba(255,255,255,.55)"}}>
                        <svg className="w-3.5 h-3.5 shrink-0 mt-0.5 fill-none" stroke="#f59e0b" strokeWidth="2.5" viewBox="0 0 24 24"><polyline points="20 6 9 17 4 12"/></svg>
                        <span dangerouslySetInnerHTML={{__html:item.replace(/^([^—]+)/,'<strong style="color:white;font-weight:600">$1</strong>')}}/>
                      </li>
                    ))}
                  </ul>
                  <button onClick={()=>setModalOpen(true)} className="w-full py-4 text-black font-extrabold text-[13px] rounded-[10px] transition-all tracking-[.3px]" style={{background:"#f59e0b",boxShadow:"0 0 36px rgba(245,158,11,.28)"}}>
                    Get Instant Access — $297 →
                  </button>
                  <p className="text-center text-[10px] mt-2.5 tracking-[.2px]" style={{color:"rgba(255,255,255,.25)"}}>Stripe encrypted · Instant delivery · 30-day money back</p>
                </div>
              </div>
            </div>
          </div>
        </section>

        {/* FAQ */}
        <section id="faq" className="py-24 px-7" style={{background:"#06080f",borderTop:"1px solid rgba(255,255,255,.07)"}}>
          <div className="max-w-[1100px] mx-auto">
            <div className="flex items-center gap-2 text-[10px] font-bold uppercase tracking-[3px] mb-3.5" style={{color:"#f59e0b"}}><span className="w-5 h-px" style={{background:"#f59e0b"}}/>FAQ</div>
            <h2 className="font-extrabold tracking-[-1.5px] mb-10" style={{fontSize:"clamp(26px,2.8vw,42px)"}}>Common questions.</h2>
            <div className="max-w-[640px]" style={{borderTop:"1px solid rgba(255,255,255,.07)"}}>
              {faqs.map((f,i)=>(
                <div key={i} style={{borderBottom:"1px solid rgba(255,255,255,.07)"}}>
                  <button className="w-full flex items-center justify-between py-5 text-left text-[14px] font-medium transition-colors gap-4" style={{color:openFaq===i?"#fff":"rgba(255,255,255,.55)"}} onClick={()=>setOpenFaq(openFaq===i?null:i)}>
                    {f.q}
                    <div className="w-6 h-6 rounded-[6px] flex items-center justify-center text-[16px] shrink-0 transition-transform" style={{background:openFaq===i?"rgba(245,158,11,.08)":"rgba(255,255,255,.06)",border:openFaq===i?"1px solid rgba(245,158,11,.25)":"1px solid rgba(255,255,255,.07)",color:"#f59e0b",transform:openFaq===i?"rotate(45deg)":"none"}}>+</div>
                  </button>
                  {openFaq===i&&<div className="pb-5 text-[13px] leading-[1.9]" style={{color:"rgba(255,255,255,.5)"}}>{f.a}</div>}
                </div>
              ))}
            </div>
          </div>
        </section>

        {/* Footer */}
        <footer style={{borderTop:"1px solid rgba(255,255,255,.07)"}}>
          <div className="max-w-[1100px] mx-auto px-7 py-6 flex flex-wrap items-center justify-between gap-3">
            <a href="#" className="flex items-center gap-2 text-[13px] font-bold no-underline" style={{color:"rgba(255,255,255,.55)"}}>
              <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="#f59e0b" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"><polyline points="22 7 13.5 15.5 8.5 10.5 2 17"/><polyline points="16 7 22 7 22 13"/></svg>
              Apex Trade Bot
            </a>
            <div className="flex gap-4">
              {[["Privacy","/privacy"],["Terms","/terms"],["Support","mailto:support@aicashsystem.space"]].map(([l,h])=>(
                <a key={l} href={h} className="text-[11px] no-underline transition-colors" style={{color:"rgba(255,255,255,.25)"}}>{l}</a>
              ))}
            </div>
            <div className="text-[11px]" style={{color:"rgba(255,255,255,.25)"}}>© 2025 AICashSystem · aicashsystem.space</div>
          </div>
          <div className="max-w-[1100px] mx-auto px-7 pb-6 text-center text-[10px] leading-[1.7]" style={{color:"rgba(255,255,255,.15)"}}>
            Apex Trade Bot is an automation software tool sold as source code. It is not financial advice. Crypto trading involves substantial risk of loss. All performance figures are from simulated demo environments. Past performance is not indicative of future results. Always use paper trading mode before trading with real capital.
          </div>
        </footer>
      </div>
    </>
  );
}
