#!/usr/bin/env python3
"""Apex Trade Bot — TikTok / Reels generator (9:16, local, no paid API).

Renders branded vertical videos: dark fintech background, animated red
candlestick logo, big hook text, and a clear CTA. Output is ready to post
on TikTok / Instagram Reels / YouTube Shorts.

Run:
    python scripts/make_bot_tiktok.py            # render all videos
    python scripts/make_bot_tiktok.py v1         # render one by id

Add a voiceover later in CapCut using the printed VO script, or use the bot's
on-screen text as-is (silent + trending audio works well on TikTok).
"""
import os
import sys
import math
from pathlib import Path

os.environ.setdefault("IMAGEIO_FFMPEG_EXE", __import__("imageio_ffmpeg").get_ffmpeg_exe())

from PIL import Image, ImageDraw, ImageFont      # noqa: E402
from moviepy import ImageClip, concatenate_videoclips  # noqa: E402
import numpy as np  # noqa: E402

OUTPUT_DIR = Path(__file__).resolve().parent.parent / "outputs" / "bot-tiktok"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# ── Brand palette (matches the site) ─────────────────────────────────────────
W, H = 1080, 1920
BG       = (6, 6, 8)          # --bg
PANEL    = (17, 17, 21)       # --panel
ACC      = (255, 45, 79)      # --acc  red
ACC2     = (255, 92, 116)     # --acc2 light red
UP       = (39, 196, 106)     # green
T0       = (245, 245, 247)    # white text
T1       = (150, 150, 160)    # muted text
FPS      = 30

# ── Video scripts ────────────────────────────────────────────────────────────
VIDEOS = [
    {
        "id": "v1",
        "tag": "CRYPTO · $297",
        "beats": [
            {"text": "I let an AI bot\ntrade crypto for me", "size": 84, "accent": True},
            {"text": "It runs 24/7 on my own\nBinance account.", "size": 64},
            {"text": "I control everything\nfrom Telegram.", "size": 66},
            {"text": "Not a subscription.\nI own the bot.", "size": 70, "accent": True},
            {"text": "Apex Trade Bot — $297\nLink in bio.", "size": 64, "accent": True},
        ],
        "vo": "I let an AI bot trade crypto for me. It runs twenty four seven on my own "
              "Binance account. I control everything from Telegram. It's not a subscription "
              "— I own the bot. Apex Trade Bot, two hundred ninety seven dollars. Link in bio.",
    },
    {
        "id": "v2",
        "tag": "PASSIVE INCOME",
        "beats": [
            {"text": "Everyone wants passive\nincome. Nobody wants\nto stare at charts.", "size": 60},
            {"text": "So I automated it.", "size": 84, "accent": True},
            {"text": "An AI bot that analyzes\nthe market and trades —\nwhile I sleep.", "size": 56},
            {"text": "Your keys. Your account.\nYour money stays yours.", "size": 58, "accent": True},
            {"text": "Apex Trade Bot.\nLink in bio.", "size": 70, "accent": True},
        ],
        "vo": "Everyone wants passive income. Nobody wants to stare at charts. So I automated it. "
              "An AI bot that analyzes the market and trades while I sleep. Your keys, your account, "
              "your money stays yours. Apex Trade Bot. Link in bio.",
    },
    {
        "id": "v3",
        "tag": "FOREX · $497",
        "beats": [
            {"text": "What if your forex account\ntraded itself?", "size": 64, "accent": True},
            {"text": "Connect OANDA or MT5.\nSet your risk. Done.", "size": 58},
            {"text": "The AI handles entries,\nstops and take-profits.", "size": 58},
            {"text": "Start in paper mode.\nGo live when ready.", "size": 60, "accent": True},
            {"text": "Apex Forex Bot — $497\nLink in bio.", "size": 62, "accent": True},
        ],
        "vo": "What if your forex account traded itself? Connect OANDA or MT5, set your risk, done. "
              "The AI handles entries, stops and take profits. Start in paper mode, go live when "
              "you're ready. Apex Forex Bot, four hundred ninety seven dollars. Link in bio.",
    },
    {
        "id": "v4",
        "tag": "HOW IT WORKS",
        "beats": [
            {"text": "Buy the bot once.", "size": 80, "accent": True},
            {"text": "Paste your exchange\nAPI key in the setup page.", "size": 56},
            {"text": "Click deploy.\nIt's live in 10 minutes.", "size": 60},
            {"text": "No coding.\nNo monthly fees.", "size": 70, "accent": True},
            {"text": "aicashsystem.space", "size": 64, "accent": True},
        ],
        "vo": "Buy the bot once. Paste your exchange API key in the setup page. Click deploy — "
              "it's live in ten minutes. No coding, no monthly fees. Apex Trade Bot at "
              "aicashsystem dot space.",
    },
]


def font(size, bold=True):
    name = "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf"
    for base in ("/usr/share/fonts/truetype/dejavu/", "/usr/share/fonts/", "/System/Library/Fonts/"):
        p = base + name
        if os.path.exists(p):
            return ImageFont.truetype(p, size)
    return ImageFont.load_default()


def draw_logo(draw, cx, top, scale=1.0):
    """The 3 ascending red candlestick bars + circle, scaled."""
    def s(v):
        return v * scale
    bars = [(-90, 70, 36, 90, 115), (-30, 35, 36, 125, 184), (30, 0, 36, 165, 255)]
    for (dx, dy, w, h, a) in bars:
        x0 = cx + s(dx)
        y0 = top + s(dy)
        draw.rounded_rectangle([x0, y0, x0 + s(w), y0 + s(h)], radius=s(18),
                               fill=ACC + (a,))
    # circle on top of tallest bar
    cxr = cx + s(48)
    cyr = top + s(-8)
    r = s(22)
    draw.ellipse([cxr - r, cyr - r, cxr + r, cyr + r], fill=ACC2)


def grid_bg(img):
    """Subtle fintech grid + red glow."""
    draw = ImageDraw.Draw(img, "RGBA")
    # glow
    glow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow)
    gd.ellipse([W * 0.1, H * 0.18, W * 0.9, H * 0.62], fill=(255, 45, 79, 46))
    from PIL import ImageFilter
    glow = glow.filter(ImageFilter.GaussianBlur(160))
    img.alpha_composite(glow)
    # faint grid lines
    for x in range(0, W, 90):
        draw.line([(x, 0), (x, H)], fill=(255, 255, 255, 6), width=1)
    for y in range(0, H, 90):
        draw.line([(0, y), (W, y)], fill=(255, 255, 255, 6), width=1)


def make_frame(text, accent, size, tag, progress):
    img = Image.new("RGBA", (W, H), BG + (255,))
    grid_bg(img)
    draw = ImageDraw.Draw(img, "RGBA")

    # logo (animated subtle bob)
    bob = int(math.sin(progress * math.pi) * 6)
    draw_logo(draw, W // 2, 230 + bob, scale=1.0)

    # tag pill
    tf = font(30)
    tw = draw.textbbox((0, 0), tag, font=tf)[2]
    pill_w = tw + 56
    px = (W - pill_w) // 2
    draw.rounded_rectangle([px, 470, px + pill_w, 524], radius=27,
                           fill=(255, 45, 79, 30), outline=ACC + (160,), width=2)
    draw.text((W // 2, 497), tag, font=tf, fill=ACC2, anchor="mm")

    # main text (center)
    color = ACC2 if accent else T0
    f = font(size)
    lines = text.split("\n")
    line_h = int(size * 1.18)
    total_h = len(lines) * line_h
    y = H // 2 - total_h // 2 + 40
    for ln in lines:
        draw.text((W // 2, y), ln, font=f, fill=color, anchor="mm")
        y += line_h

    # progress bar at bottom
    bar_y = H - 120
    draw.rounded_rectangle([90, bar_y, W - 90, bar_y + 8], radius=4, fill=(255, 255, 255, 26))
    draw.rounded_rectangle([90, bar_y, 90 + int((W - 180) * progress), bar_y + 8], radius=4, fill=ACC + (255,))

    # footer brand
    ff = font(26, bold=False)
    draw.text((W // 2, H - 70), "APEX TRADE BOT", font=ff, fill=T1, anchor="mm")

    return np.array(img.convert("RGB"))


def render(video):
    clips = []
    n = len(video["beats"])
    for i, beat in enumerate(video["beats"]):
        dur = beat.get("duration", 3.6)
        frame = make_frame(beat["text"], beat.get("accent", False),
                           beat["size"], video["tag"], (i + 1) / n)
        clips.append(ImageClip(frame).with_duration(dur).with_fps(FPS))
    final = concatenate_videoclips(clips, method="compose")
    out = OUTPUT_DIR / f"apex_{video['id']}.mp4"
    final.write_videofile(str(out), fps=FPS, codec="libx264", audio=False,
                          preset="medium", logger=None)
    print(f"✅ {out.name}  ({final.duration:.1f}s)")
    print(f"   🎙  VO: {video['vo']}\n")
    return out


def main():
    want = sys.argv[1] if len(sys.argv) > 1 else None
    todo = [v for v in VIDEOS if not want or v["id"] == want]
    if not todo:
        print(f"No video with id '{want}'. Available: {[v['id'] for v in VIDEOS]}")
        return
    for v in todo:
        render(v)
    print(f"All videos in: {OUTPUT_DIR}")


if __name__ == "__main__":
    main()
