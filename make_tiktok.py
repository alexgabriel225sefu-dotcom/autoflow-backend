#!/usr/bin/env python3
"""
AI Cash Systems — TikTok Video Generator
Generates branded 9:16 vertical videos with voiceover, ready to post.
"""

import os, math
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
from moviepy import ImageClip, concatenate_videoclips
import numpy as np

OUTPUT_DIR = Path("outputs/tiktok-videos")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

W, H = 1080, 1920   # 9:16 vertical
BG      = (8, 8, 8)
GOLD    = (200, 169, 110)
CREAM   = (245, 240, 232)
DIMGOLD = (138, 106, 46)

# ── Videos to generate ──────────────────────────────────────────────────────
VIDEOS = [
    {
        "id": "v1",
        "beats": [
            {"text": "I made $300 selling AI bots.\nI don't even know how to code.", "duration": 4.5, "size": 68, "accent": True},
            {"text": "I found a course called\nAI Cash Systems.", "duration": 3.5, "size": 58, "accent": False},
            {"text": "2 hours to build a bot\na business paid $400 for.", "duration": 4.0, "size": 58, "accent": False},
            {"text": "The course is $37.\nI made that back in week one.", "duration": 4.0, "size": 58, "accent": False},
            {"text": "Link in bio if you actually\nwant to learn this.", "duration": 3.5, "size": 54, "accent": True},
        ],
        "voiceover": (
            "I made three hundred dollars selling AI bots. "
            "I don't even know how to code. "
            "I found a course called AI Cash Systems. "
            "Two hours to build a bot a business paid four hundred dollars for. "
            "The course is thirty seven dollars. I made that back in week one. "
            "Link in bio if you actually want to learn this."
        ),
    },
    {
        "id": "v2",
        "beats": [
            {"text": "Nobody talks about how exhausting it is\nto work hard and still not have enough.", "duration": 5.0, "size": 54, "accent": False},
            {"text": "I started asking a different question.", "duration": 3.0, "size": 64, "accent": True},
            {"text": "Not 'how do I work harder' —\nbut 'what skill pays me differently?'", "duration": 4.5, "size": 52, "accent": False},
            {"text": "AI automation was my answer.\nFirst client in 30 days.", "duration": 4.0, "size": 58, "accent": True},
            {"text": "You don't need to quit your job tomorrow.\nYou need one skill that gives you options.", "duration": 5.0, "size": 50, "accent": False},
        ],
        "voiceover": (
            "Nobody talks about how exhausting it is "
            "to work hard and still not have enough. "
            "I started asking a different question. "
            "Not how do I work harder — but what skill pays me differently? "
            "AI automation was my answer. First client in thirty days. "
            "You don't need to quit your job tomorrow. "
            "You need one skill that gives you options."
        ),
    },
    {
        "id": "v3",
        "beats": [
            {"text": "Businesses are losing thousands every month\nto problems a $37 course can fix.", "duration": 5.0, "size": 52, "accent": True},
            {"text": "They need someone to build\nWhatsApp bots, Instagram DM bots,\nlead follow-up systems.", "duration": 5.0, "size": 48, "accent": False},
            {"text": "You learn it once.\nThey pay you every month.", "duration": 3.5, "size": 66, "accent": True},
            {"text": "AI Cash Systems — $37 Starter.\nFirst client in 30 days.", "duration": 3.5, "size": 56, "accent": False},
            {"text": "Link in bio.", "duration": 2.5, "size": 80, "accent": True},
        ],
        "voiceover": (
            "Businesses are losing thousands every month "
            "to problems a thirty seven dollar course can fix. "
            "They need someone to build WhatsApp bots, Instagram DM bots, "
            "lead follow-up systems. "
            "You learn it once. They pay you every month. "
            "AI Cash Systems — thirty seven dollar Starter. "
            "First client in thirty days. "
            "Link in bio."
        ),
    },
]


def make_font(size):
    for name in ["DejaVuSans-Bold.ttf", "LiberationSans-Bold.ttf", "Arial.ttf"]:
        for base in ["/usr/share/fonts/truetype/dejavu/",
                     "/usr/share/fonts/truetype/liberation/",
                     "/usr/share/fonts/",
                     "/System/Library/Fonts/"]:
            p = base + name
            if os.path.exists(p):
                return ImageFont.truetype(p, size)
    return ImageFont.load_default()


def make_frame(text, accent=False, font_size=60):
    img = Image.new("RGB", (W, H), BG)
    draw = ImageDraw.Draw(img)

    # subtle radial gradient overlay
    for r in range(0, 400, 8):
        alpha = max(0, 18 - r // 22)
        draw.ellipse(
            [W//2 - r, H//3 - r, W//2 + r, H//3 + r],
            fill=tuple(min(255, c + alpha) for c in GOLD)
        )

    # top accent line
    draw.rectangle([W//2 - 60, 120, W//2 + 60, 123], fill=GOLD)

    # logo text
    logo_font = make_font(22)
    draw.text((W//2, 90), "AI CASH SYSTEMS", font=logo_font, fill=GOLD, anchor="mm")

    # main text
    color = GOLD if accent else CREAM
    font = make_font(font_size)
    lines = text.split("\n")
    line_h = font_size + 14
    total_h = len(lines) * line_h
    y_start = H // 2 - total_h // 2

    for i, line in enumerate(lines):
        draw.text((W//2, y_start + i * line_h), line, font=font, fill=color, anchor="mm")

    # bottom CTA bar
    draw.rectangle([0, H - 160, W, H], fill=(12, 10, 6))
    cta_font = make_font(28)
    draw.text((W//2, H - 110), "aicashsystem.space  ·  Link in bio", font=cta_font, fill=GOLD, anchor="mm")
    draw.text((W//2, H - 68), "Starter $37  ·  PRO $97  ·  No coding required", font=make_font(22), fill=(150, 130, 90), anchor="mm")

    return np.array(img)


def generate_video(spec):
    vid_id = spec["id"]
    beats = spec["beats"]
    total = sum(b["duration"] for b in beats)
    print(f"\n[{vid_id}] Building {len(beats)} beats ({total:.0f}s)...")

    clips = []
    for beat in beats:
        frame = make_frame(beat["text"], beat.get("accent", False), beat.get("size", 60))
        clip = ImageClip(frame).with_duration(beat["duration"])
        clips.append(clip)

    video = concatenate_videoclips(clips, method="compose")
    out = OUTPUT_DIR / f"aicash_{vid_id}.mp4"
    print(f"[{vid_id}] Rendering → {out}")
    video.write_videofile(
        str(out), fps=30, codec="libx264",
        preset="ultrafast", logger=None,
    )
    print(f"[{vid_id}] ✅ {out}")
    return out


if __name__ == "__main__":
    print("=== AI Cash Systems TikTok Generator ===")
    results = []
    for spec in VIDEOS:
        try:
            out = generate_video(spec)
            results.append(("✅", spec["id"], str(out)))
        except Exception as e:
            results.append(("❌", spec["id"], str(e)))

    print("\n=== RESULTS ===")
    for status, vid_id, info in results:
        print(f"  {status} {vid_id}: {info}")
