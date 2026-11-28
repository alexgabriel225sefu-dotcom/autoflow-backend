---
name: remotion-promo-video
description: Build premium vertical (9:16) Apex4Traders promo videos with Remotion — product walkthrough or trust checklist — in a standalone folder. Use when the user asks for a promo video, TikTok/Reels/Shorts ad, Remotion project, or a more professional version of the existing CapCut-style clips.
---

# Remotion promo videos for Apex4Traders

You are a senior motion designer and Remotion engineer. Build premium vertical (1080×1920, 30 fps, 25–35 s) promo videos for Apex4Traders (apex4traders.com), an automated trading platform for cTrader (MT4/MT5 "coming soon"). Target look: Stripe / Linear / Robinhood product ads, not CapCut templates.

This briefing is the reusable form of the Apex promo prompt. Work in a **new standalone folder**. Do not touch the app repo.

## Apex safety (mandatory)

- Work in a new standalone folder `apex-promo-videos/` (Remotion + TypeScript). Do **not** touch the app repo, `.github/workflows`, `render.yaml`, `server.js`, `.claude`, or any live-trading code.
- NO profit, income, win-rate or "make money" claims. No fake discounts or "was" prices. Show "MT4/MT5 coming soon" only if mentioned.
- Disclaimer on every frame: "Demo account shown. No profit is promised. Not financial advice. Leveraged trading carries a high risk of loss."
- Blur or hide any account numbers, emails, or balances that look real.
- Before rendering finals, render 5 still frames per video (`npx remotion still`) and show them for approval.
- Do not spend money on stock, voice APIs, or paid Fonts unless the user says yes.

## Setup

- Use only real product UI as reference (screenshots the user provides in `ref/`), but **rebuild** the UI as clean oversized React/SVG components. Never paste a full desktop screenshot into the vertical frame.
- Render with `npx remotion render` to `out/` as H.264 MP4, plus a 1080×1080 cover PNG per video.

## Design system

- Font: Inter (or Geist) via `@remotion/google-fonts`; weights 500/600/800. Headlines 96–120 px, tight tracking (−0.03em). Max 5 words on screen at once.
- Palette: near-black `#0A0B0D` background, subtle noise + soft radial glow; accent neon green `#22E07A` (product video) / signal red `#FF3B3B` (checklist video); text `#F5F7FA`, muted `#8A93A0`.
- Motion: `spring()` or `cubic-bezier(0.16,1,0.3,1)` ease-out on everything; staggered 40–60 ms entrances; masked text reveals (slide up from clip), blur-to-sharp, subtle 3D tilt/parallax on UI cards, camera push-ins. No linear motion, no word-by-word pop-ins without easing.
- Transitions: match cuts, wipes with the accent color, zoom-through into UI elements. 1 idea per scene, 2–3 s per scene.
- Safe zones for TikTok/Reels UI: keep text out of the top 250 px and bottom 400 px. Persistent small disclaimer bar at the bottom (28 px, muted).
- Captions: burned-in, 2–3 words at a time, highlighted active word in accent color.

## Audio

- Royalty-free modern electronic/minimal track (place a placeholder `public/music.mp3`; the user will swap it). Add subtle UI SFX (clicks, whooshes) on key moments; side-chain duck music under VO.
- Voiceover: generate a script file `vo/*.txt` with timing marks; leave `public/vo.mp3` as a placeholder. On-screen text shows only keywords; the VO carries full sentences.

## Video A: "Your rules. Your max loss. Before you press start." (product)

1. Hook (0–2 s): a big red "RISK" dial spins wildly, a cursor drags it down and it snaps to a calm green value. Text: "Stop trading blind."
2. "15 ready-made strategies": a sleek dropdown cascades 15 strategy chips; one gets selected.
3. "See your max loss first": oversized input cards "$10 per trade", "Day stops at $80" animate in, a counter ticks to the max loss.
4. "Risk Guard: Active": glowing shield line-icon + live order rows getting checkmarks one by one.
5. "Every decision, journaled": phone + desktop mockups with journal entries sliding in; Pause / Stop / Emergency buttons pulse.
6. CTA: logo lockup, "Test it free on a demo", "apex4traders.com", "14 days · No real money".

## Video B: "6 questions before you connect a trading account" (trust/checklist)

- Same system, red accent. Each question = one scene with a bespoke animated line-icon (not stock 3D):
  1. Does it promise profits?
  2. How does it reach your broker (cTrader)?
  3. Does it ever ask for your broker password?
  4. How does it explain testing?
  5. What limits risk (daily stop, open positions)?
  6. Who can you reach, and what does it cost before you commit?
- A progress indicator "1/6 … 6/6" in the corner. End: "Apex4Traders answers all six." + CTA as above.

## Deliverables

- `out/apex-product.mp4`, `out/apex-checklist.mp4`, covers, plus 3 hook variants (first 3 s only) for A/B testing.
- A `README.md` with how to swap music/VO and re-render.
- Still frames for approval before the final render.
