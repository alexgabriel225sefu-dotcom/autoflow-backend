"use client";

import React, { useEffect, useRef, useState } from "react";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { FaApple } from "react-icons/fa";
import { FcGoogle } from "react-icons/fc";
import { Lock, ShieldCheck } from "lucide-react";

declare global {
  interface Window { Stripe: any; }
}

interface PaymentFormProps {
  onClose?: () => void;
}

export default function ModernPaymentForm({ onClose }: PaymentFormProps) {
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [checks, setChecks] = useState([false, false, false]);
  const [error, setError] = useState("");
  const [infoMsg, setInfoMsg] = useState("");
  const [loading, setLoading] = useState(false);
  const [success, setSuccess] = useState(false);
  const stripeRef = useRef<any>(null);
  const cardNumRef = useRef<any>(null);
  const cardExpRef = useRef<any>(null);
  const cardCvcRef = useRef<any>(null);

  const allChecked = checks.every(Boolean);

  useEffect(() => {
    if (!window.Stripe) return;
    if (stripeRef.current) return;
    stripeRef.current = window.Stripe(process.env.NEXT_PUBLIC_STRIPE_PK!);
    const els = stripeRef.current.elements({
      appearance: {
        theme: "night",
        variables: {
          colorPrimary: "#f59e0b",
          colorBackground: "#0d1017",
          colorText: "#ffffff",
          borderRadius: "8px",
          fontFamily: "var(--font-geist-sans), system-ui, sans-serif",
        },
      },
    });
    const style = {
      base: {
        color: "#fff",
        fontSize: "14px",
        "::placeholder": { color: "rgba(255,255,255,0.25)" },
      },
      invalid: { color: "#ef4444" },
    };
    cardNumRef.current = els.create("cardNumber", { style, showIcon: true, placeholder: "0000 0000 0000 0000" });
    cardExpRef.current = els.create("cardExpiry", { style, placeholder: "MM / YY" });
    cardCvcRef.current = els.create("cardCvc", { style, placeholder: "CVV" });
    cardNumRef.current.mount("#stripe-cardnumber");
    cardExpRef.current.mount("#stripe-cardexpiry");
    cardCvcRef.current.mount("#stripe-cardcvc");
    cardNumRef.current.on("change", (e: any) => {
      if (e.error) { setError(e.error.message); } else { setError(""); }
    });
  }, []);

  const handleWallet = (type: "apple" | "google") => {
    setError("");
    setInfoMsg(`${type === "apple" ? "Apple Pay" : "Google Pay"} is available if your browser supports it. Otherwise use the card form below.`);
  };

  const handleSubmit = async () => {
    setError(""); setInfoMsg("");
    if (!name) { setError("Please enter your name."); return; }
    if (!email || !email.includes("@")) { setError("Please enter a valid email."); return; }
    setLoading(true);
    try {
      const r = await fetch("/api/create-payment-intent", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ amount: 29700, currency: "usd", email, name, product: "apex-bot" }),
      });
      const d = await r.json();
      if (d.error) { setError(d.error); setLoading(false); return; }
      const result = await stripeRef.current.confirmCardPayment(d.clientSecret, {
        payment_method: { card: cardNumRef.current, billing_details: { name, email } },
      });
      if (result.error) {
        setError(result.error.message);
        setLoading(false);
      } else if (result.paymentIntent.status === "succeeded") {
        setSuccess(true);
        const redirect = "/configurator" + (d.pendingKey ? `?key=${encodeURIComponent(d.pendingKey)}` : "");
        setTimeout(() => { window.location.href = redirect; }, 2000);
      }
    } catch (e: any) {
      setError("Error: " + e.message);
      setLoading(false);
    }
  };

  if (success) {
    return (
      <Card className="max-w-md w-full rounded-2xl border-amber-500/20">
        <CardContent className="p-10 flex flex-col items-center text-center gap-4">
          <div className="w-14 h-14 rounded-2xl bg-amber-500/10 border border-amber-500/20 flex items-center justify-center">
            <ShieldCheck className="w-7 h-7 text-amber-500" />
          </div>
          <h3 className="text-xl font-bold text-amber-500">Access Granted</h3>
          <p className="text-sm text-white/60 leading-relaxed">Redirecting to your setup page...<br/>Your license key and bot configurator are ready.</p>
        </CardContent>
      </Card>
    );
  }

  return (
    <Card className="max-w-md w-full rounded-2xl border-white/10 shadow-2xl bg-[#07090f]">
      <CardContent className="p-0">
        {/* Header */}
        <div className="px-6 pt-6 pb-5 text-center border-b border-white/08">
          <div className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full border border-amber-500/20 bg-amber-500/05 text-amber-500/70 text-[10px] font-semibold tracking-widest uppercase mb-3">
            <Lock className="w-2.5 h-2.5" /> Secure Checkout
          </div>
          <h2 className="text-[19px] font-extrabold tracking-tight mb-1">Complete Your Order</h2>
          <p className="text-xs text-white/40 mb-4">One-time purchase · Full source code · Instant delivery</p>
          <div className="inline-flex items-baseline gap-2 px-5 py-2.5 rounded-xl bg-amber-500/08 border border-amber-500/15">
            <span className="text-3xl font-black text-amber-500 tracking-tighter">$297</span>
            <span className="text-sm text-white/30 line-through">$497</span>
            <span className="text-[9px] text-white/30 uppercase tracking-widest self-center">one-time</span>
          </div>
        </div>

        {/* Body */}
        <div className="p-6 space-y-4">
          {/* Wallet buttons — NO PayPal */}
          <div className="grid grid-cols-2 gap-3">
            <Button variant="outline" className="h-12 border-white/10 bg-[#0d1017] hover:bg-[#131924] text-white gap-2 text-sm font-semibold" onClick={() => handleWallet("apple")}>
              <FaApple size={18} /> Apple Pay
            </Button>
            <Button variant="outline" className="h-12 border-white/10 bg-[#0d1017] hover:bg-[#131924] text-white gap-2 text-sm font-semibold" onClick={() => handleWallet("google")}>
              <FcGoogle size={20} /> Google Pay
            </Button>
          </div>

          {/* Separator */}
          <div className="flex items-center gap-3 text-white/30 text-xs">
            <hr className="flex-1 border-white/08" />
            <span className="font-medium tracking-wide">or pay using credit card</span>
            <hr className="flex-1 border-white/08" />
          </div>

          {/* Name */}
          <div className="space-y-1.5">
            <Label htmlFor="pm-name" className="text-[10px] uppercase tracking-widest text-white/40 font-semibold">Card holder full name</Label>
            <Input id="pm-name" placeholder="Enter your full name" value={name} onChange={e => setName(e.target.value)}
              className="bg-[#0d1017] border-white/08 text-white placeholder:text-white/25 focus-visible:border-amber-500/40 focus-visible:ring-amber-500/15 h-11 rounded-lg" />
          </div>

          {/* Email */}
          <div className="space-y-1.5">
            <Label htmlFor="pm-email" className="text-[10px] uppercase tracking-widest text-white/40 font-semibold">Email — license key delivery</Label>
            <Input id="pm-email" type="email" placeholder="you@email.com" value={email} onChange={e => setEmail(e.target.value)}
              className="bg-[#0d1017] border-white/08 text-white placeholder:text-white/25 focus-visible:border-amber-500/40 focus-visible:ring-amber-500/15 h-11 rounded-lg" />
          </div>

          {/* Card number */}
          <div className="space-y-1.5">
            <Label className="text-[10px] uppercase tracking-widest text-white/40 font-semibold">Card Number</Label>
            <div id="stripe-cardnumber" className="h-11 rounded-lg border border-white/08 bg-[#0d1017] px-3 flex items-center transition-colors focus-within:border-amber-500/40" />
          </div>

          {/* Expiry / CVV */}
          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-1.5">
              <Label className="text-[10px] uppercase tracking-widest text-white/40 font-semibold">Expiry Date</Label>
              <div id="stripe-cardexpiry" className="h-11 rounded-lg border border-white/08 bg-[#0d1017] px-3 flex items-center transition-colors focus-within:border-amber-500/40" />
            </div>
            <div className="space-y-1.5">
              <Label className="text-[10px] uppercase tracking-widest text-white/40 font-semibold">CVV</Label>
              <div id="stripe-cardcvc" className="h-11 rounded-lg border border-white/08 bg-[#0d1017] px-3 flex items-center transition-colors focus-within:border-amber-500/40" />
            </div>
          </div>

          {/* Error / Info */}
          {error && <p className="text-xs text-red-400 font-mono min-h-4">{error}</p>}
          {infoMsg && !error && <p className="text-xs text-white/40 font-mono min-h-4">{infoMsg}</p>}

          {/* Checkboxes */}
          <div className="space-y-2 pt-1">
            {[
              <>I accept the <strong className="text-white/60">risk of loss</strong> — crypto trading involves significant financial risk.</>,
              <>This is <strong className="text-white/60">NOT financial advice</strong>. Sales are final after digital delivery.</>,
              <>I agree to the <a href="/terms" target="_blank" className="text-amber-500/70 hover:text-amber-500">Terms</a> and <a href="/privacy" target="_blank" className="text-amber-500/70 hover:text-amber-500">Privacy Policy</a>.</>,
            ].map((label, i) => (
              <label key={i} className="flex items-start gap-2.5 cursor-pointer">
                <input type="checkbox" checked={checks[i]} onChange={e => setChecks(c => c.map((v, j) => j === i ? e.target.checked : v))}
                  className="mt-0.5 w-3.5 h-3.5 shrink-0 accent-amber-500 cursor-pointer" />
                <span className="text-[11px] text-white/35 leading-relaxed">{label}</span>
              </label>
            ))}
          </div>

          {/* Submit */}
          <Button className="w-full h-12 bg-amber-500 hover:bg-amber-400 text-black font-extrabold text-sm tracking-wide shadow-[0_0_32px_rgba(245,158,11,0.22)] transition-all"
            disabled={!allChecked || loading} onClick={handleSubmit}>
            {loading ? (
              <span className="flex items-center gap-2">
                <span className="w-3.5 h-3.5 border-2 border-black/20 border-t-black rounded-full animate-spin" />
                Processing...
              </span>
            ) : "Checkout — $297"}
          </Button>

          <p className="text-center text-[10px] text-white/25 tracking-wide flex items-center justify-center gap-1.5">
            <Lock className="w-3 h-3" /> Secured by Stripe · Instant delivery · No subscription
          </p>
        </div>
      </CardContent>
    </Card>
  );
}
