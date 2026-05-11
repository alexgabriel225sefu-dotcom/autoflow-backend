#!/usr/bin/env python3
"""
AI Cash Systems — TikTok Video Generator v2
Faceless cinematic B-roll: screen footage, payment proofs, automation builds.
Each clip 8s (Veo 3 max). Stack in CapCut for 30s+ TikToks.
"""

import os, time, requests
from pathlib import Path

API_KEY = os.environ.get("GOOGLE_AI_API_KEY", "AIzaSyAEk3AtQMQMq6gqV1hWr_ezW2LfVQMNMVU")
OUTPUT_DIR = Path("outputs/tiktok-v2")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

VIDEOS = [
    {
        "id": "t1",
        "title": "Stripe payment notification",
        "prompt": """Extreme close-up cinematic vertical 9:16 shot of a smartphone screen on a wooden desk.
The screen suddenly lights up showing a Stripe app notification: 'Payment received — $347.00 — AI Automation Setup — Marcus D.'
A second notification slides in: '$199.00 — Monthly retainer — Sarah K.'
A relaxed hand picks up the phone and scrolls through the Stripe payments list — 6 payments this week, $1,491 total.
Warm afternoon sunlight through a window. Real scratches on phone case. Authentic home desk.
Everything looks genuinely real — not staged. Documentary mobile cinematography. Vertical 9:16."""
    },
    {
        "id": "t2",
        "title": "Make.com automation being built",
        "prompt": """Cinematic vertical 9:16 close-up of a laptop screen showing Make.com (formerly Integromat) automation builder.
Hands with natural imperfections are connecting modules fast: a webhook trigger connects to an OpenAI module, which connects to a Gmail sender, which connects to a Google Sheets logger.
The workflow snaps together cleanly. User clicks 'Run once' — all modules flash green with checkmarks.
A small popup appears: 'Scenario ran successfully. 1 operation used.'
Screen glow illuminates the workspace. Coffee cup edge visible. Late afternoon light.
Text on screen typed in a notepad: 'Client 3 — $400 — DONE.'
Real, focused, skilled work energy. No face visible. Vertical 9:16 cinematic."""
    },
    {
        "id": "t3",
        "title": "AI chatbot responding instantly",
        "prompt": """Cinematic vertical 9:16 close-up of a laptop screen showing a live chatbot test interface.
Someone types a test message: 'What are your business hours?'
The AI bot responds in 0.4 seconds with a perfect, professional answer.
They type: 'I want to book a consultation.'
Bot instantly replies with a Calendly booking link and a personalized message.
They type: 'Do you offer payment plans?'
Bot answers immediately, perfectly.
The tester leans back. Opens a new browser tab showing an invoice for $399 — 'AI Customer Service Bot — Setup Fee'.
Screen brightness on a clean desk, focused mood, real working environment. Vertical 9:16."""
    },
    {
        "id": "t4",
        "title": "Upwork client message + payment",
        "prompt": """Cinematic vertical 9:16 close-up of a laptop screen showing an Upwork messages interface.
An unread message from a client: 'This is incredible. The bot handled 47 customer inquiries overnight without me touching anything. When can we add it to our second location?'
The freelancer's cursor moves to the 'Send Offer' button. Types a new proposal: 'Second location setup — $299.'
Client accepts in 8 seconds. A green notification: 'Offer accepted. Funds in escrow.'
Another tab opens showing total Upwork earnings this month: $2,140.
Real browser, real interface details, authentic freelancer desk setup. Evening screen glow. Vertical 9:16 cinematic."""
    },
    {
        "id": "t5",
        "title": "Morning — 3 payments while sleeping",
        "prompt": """Cinematic vertical 9:16 shot. Morning light. A phone face-down on a nightstand.
An alarm goes off — 8:14am. Hand reaches and flips the phone over.
Screen shows 3 Stripe notifications received overnight:
'$199.00 received — 2:17am'
'$80.00 received — monthly renewal — 4:51am'
'$199.00 received — 7:03am'
The hand holds the phone still for a moment. Absorbing it.
Then opens a laptop on the bed, Make.com dashboard visible — 3 automations all showing green 'Active'.
Morning light, sheets visible, real home energy. Not luxurious — just honest and real.
Documentary cinematography. Vertical 9:16."""
    },
    {
        "id": "t6",
        "title": "Building a Zapier bot — speed run",
        "prompt": """Fast-paced cinematic vertical 9:16 close-up of a laptop screen showing Zapier.
Hands build a new Zap rapidly: Trigger — 'New form submission' → Action — 'Send to OpenAI' → Action — 'Send personalized email' → Action — 'Log to Google Sheet'.
Each step connects in seconds. The Zap is turned ON — status switches to 'ON' in green.
A test form is submitted. Within 3 seconds, a personalized AI email lands in a Gmail inbox visible in another tab. The Google Sheet logs the row automatically.
Screen shows the Zap has run 847 times this month for one client.
An invoice template opens — $349/month retainer.
Focused, skilled, fast energy. Real laptop, real tools. Vertical 9:16 cinematic."""
    },
    {
        "id": "t7",
        "title": "The $37 course that started it",
        "prompt": """Cinematic vertical 9:16 close-up of a laptop screen showing a simple online course interface.
Course title visible: 'AI Cash Systems — Module 1: Your First Bot.'
A hand clicks play. The video shows a simple Make.com tutorial.
Course progress bar shows 100% complete. Date finished: 31 days ago.
Then the hand opens a new tab — Stripe dashboard. This month: $1,847.
Goes back to the course tab. Scrolls to the price — $37.
Stays on that number for 2 seconds.
The juxtaposition is clear: $37 paid → $1,847 earned.
Screen is the only light source. Quiet, contemplative mood. Real imperfect desk.
No voice. No face. Just the numbers. Vertical 9:16 documentary."""
    },
]


def generate_video(v):
    vid_id = v["id"]
    print(f"\n[{vid_id}] '{v['title']}'")

    url = f"https://generativelanguage.googleapis.com/v1beta/models/veo-3.0-generate-001:predictLongRunning?key={API_KEY}"
    body = {
        "instances": [{"prompt": v["prompt"]}],
        "parameters": {"aspectRatio": "9:16", "durationSeconds": 8},
    }

    r = requests.post(url, json=body, timeout=60)
    if r.status_code != 200:
        return ("ERR", vid_id, f"API {r.status_code}: {r.text[:200]}")

    op_name = r.json().get("name")
    print(f"[{vid_id}] Generating... (2-4 min)")
    poll_url = f"https://generativelanguage.googleapis.com/v1beta/{op_name}?key={API_KEY}"

    for i in range(60):
        time.sleep(15)
        data = requests.get(poll_url, timeout=30).json()
        if data.get("done"):
            break
        print(f"[{vid_id}] {(i+1)*15}s elapsed...")
    else:
        return ("ERR", vid_id, "Timeout")

    try:
        samples = data["response"]["generateVideoResponse"]["generatedSamples"]
        dl_url = samples[0]["video"]["uri"]
        video_bytes = requests.get(f"{dl_url}&key={API_KEY}", timeout=120).content
        out = OUTPUT_DIR / f"{vid_id}.mp4"
        out.write_bytes(video_bytes)
        print(f"[{vid_id}] Saved {len(video_bytes)/1024/1024:.1f}MB → {out}")
        return ("OK", vid_id, str(out))
    except Exception as e:
        return ("ERR", vid_id, f"{e} | {str(data)[:200]}")


if __name__ == "__main__":
    print(f"Generating {len(VIDEOS)} cinematic B-roll clips (8s each, 9:16)")

    results = []
    for v in VIDEOS:
        status, vid_id, info = generate_video(v)
        results.append((status, vid_id, info))
        if status == "ERR":
            print(f"ERROR on {vid_id}: {info}")

    print("\n=== DONE ===")
    ok = [r for r in results if r[0] == "OK"]
    print(f"{len(ok)}/{len(VIDEOS)} generated successfully")
    for s, i, info in results:
        print(f"  {'OK' if s=='OK' else 'FAIL'} {i}: {info}")
