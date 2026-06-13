#!/usr/bin/env python3
"""Apex Trade Bot — cinematic animated product demo (9:16, local, no paid API).

Real frame-by-frame animation: an animated candlestick chart that draws itself,
a live profit counter ticking up, a Telegram phone mockup with chat bubbles
sliding in, and a 3-step deploy sequence with checkmarks. Software-company grade.

Run:
    python scripts/make_bot_demo.py            # render the full demo
    python scripts/make_bot_demo.py --fast     # 20fps preview (quicker)
"""
import os
import sys
import math
from pathlib import Path

os.environ.setdefault("IMAGEIO_FFMPEG_EXE", __import__("imageio_ffmpeg").get_ffmpeg_exe())

from PIL import Image, ImageDraw, ImageFont, ImageFilter   # noqa: E402
from moviepy import VideoClip, concatenate_videoclips       # noqa: E402
import numpy as np                                          # noqa: E402

OUT = Path(__file__).resolve().parent.parent / "outputs" / "bot-tiktok"
OUT.mkdir(parents=True, exist_ok=True)

# ── Brand palette (matches the site) ─────────────────────────────────────────
W, H = 1080, 1920
BG   = (6, 6, 8)
PANEL = (17, 17, 21)
PANEL2 = (24, 24, 29)
LINE = (255, 255, 255, 18)
ACC  = (255, 45, 79)
ACC2 = (255, 92, 116)
UP   = (39, 196, 106)
DOWN = (255, 45, 79)
T0   = (245, 245, 247)
T1   = (150, 150, 160)
T2   = (86, 86, 95)
TG   = (42, 171, 238)
FPS  = 30


# ── easing ───────────────────────────────────────────────────────────────────
def clamp(x, a=0.0, b=1.0):
    return max(a, min(b, x))


def ease_out(x):
    x = clamp(x)
    return 1 - (1 - x) ** 3


def ease_in_out(x):
    x = clamp(x)
    return 3 * x * x - 2 * x * x * x


def appear(t, start, dur=0.5):
    """0→1 eased progress for an element appearing at `start` over `dur`."""
    return ease_out((t - start) / dur) if t > start else 0.0


# ── fonts ──────────────────────────────────────────────────────────────────--
_FCACHE = {}


def font(size, bold=True):
    key = (size, bold)
    if key in _FCACHE:
        return _FCACHE[key]
    name = "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf"
    mono = "DejaVuSansMono-Bold.ttf"
    paths = [f"/usr/share/fonts/truetype/dejavu/{name}",
             f"/usr/share/fonts/truetype/dejavu/{mono}"]
    for p in paths:
        if os.path.exists(p):
            f = ImageFont.truetype(p, size)
            _FCACHE[key] = f
            return f
    f = ImageFont.load_default()
    _FCACHE[key] = f
    return f


def monof(size):
    p = "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf"
    key = ("mono", size)
    if key not in _FCACHE:
        _FCACHE[key] = ImageFont.truetype(p, size) if os.path.exists(p) else font(size)
    return _FCACHE[key]


# ── shared background (built once, reused) ───────────────────────────────────
def build_bg():
    img = Image.new("RGBA", (W, H), BG + (255,))
    glow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow)
    gd.ellipse([W * 0.05, H * 0.10, W * 0.95, H * 0.55], fill=(255, 45, 79, 42))
    gd.ellipse([W * 0.2, H * 0.55, W * 1.05, H * 1.0], fill=(42, 171, 238, 18))
    glow = glow.filter(ImageFilter.GaussianBlur(170))
    img.alpha_composite(glow)
    d = ImageDraw.Draw(img, "RGBA")
    for x in range(0, W, 96):
        d.line([(x, 0), (x, H)], fill=(255, 255, 255, 7), width=1)
    for y in range(0, H, 96):
        d.line([(0, y), (W, y)], fill=(255, 255, 255, 7), width=1)
    return img


_BG = build_bg()


def new_frame():
    return _BG.copy()


def rrect(d, box, r, fill=None, outline=None, width=1):
    d.rounded_rectangle(box, radius=r, fill=fill, outline=outline, width=width)


def text_c(d, xy, s, f, fill, anchor="mm"):
    d.text(xy, s, font=f, fill=fill, anchor=anchor)


def logo(d, cx, top, scale=1.0, glow_a=255):
    def s(v):
        return v * scale
    bars = [(-78, 60, 30, 78, 120), (-26, 30, 30, 108, 188), (26, 0, 30, 142, 255)]
    for (dx, dy, w, h, a) in bars:
        x0 = cx + s(dx)
        y0 = top + s(dy)
        rrect(d, [x0, y0, x0 + s(w), y0 + s(h)], s(15), fill=ACC + (int(a * glow_a / 255),))
    cxr, cyr, r = cx + s(41), top + s(-6), s(18)
    d.ellipse([cxr - r, cyr - r, cxr + r, cyr + r], fill=ACC2 + (glow_a,))


# ── deterministic price series for the chart ─────────────────────────────────
def price_series(n=34, seed=7):
    s = [seed]

    def rnd():
        s[0] = (s[0] * 1103515245 + 12345) % 2 ** 31
        return s[0] / 2 ** 31
    out, p = [], 100.0
    drift = 0.0
    for i in range(n):
        if i % 6 == 0:
            drift = (rnd() - 0.35) * 1.1
        o = p
        p = max(60, o + drift + (rnd() - 0.5) * 2.6)
        hi = max(o, p) + rnd() * 1.4
        lo = min(o, p) - rnd() * 1.4
        out.append((o, hi, lo, p))
    return out


CANDLES = price_series()


# ═══════════════════════════════════════════════════════════════════════════
# SCENE 1 — Brand intro
# ═══════════════════════════════════════════════════════════════════════════
def scene_intro(t, dur):
    img = new_frame()
    d = ImageDraw.Draw(img, "RGBA")
    # bars grow with stagger
    gp = ease_out(t / 1.0)
    cx, top = W // 2, 560
    sc = 2.1
    bars = [(-78, 60, 30, 78, 120, 0.0), (-26, 30, 30, 108, 188, 0.15), (26, 0, 30, 142, 255, 0.3)]
    for (dx, dy, w, h, a, delay) in bars:
        g = ease_out((t - delay) / 0.7)
        if g <= 0:
            continue
        x0 = cx + dx * sc
        full_h = h * sc
        gh = full_h * g
        y_bottom = top + (dy + h) * sc
        rrect(d, [x0, y_bottom - gh, x0 + w * sc, y_bottom], 15 * sc, fill=ACC + (int(a),))
    if t > 0.55:
        ca = appear(t, 0.55, 0.4)
        cxr, cyr, r = cx + 41 * sc, top + -6 * sc, 18 * sc
        d.ellipse([cxr - r, cyr - r, cxr + r, cyr + r], fill=ACC2 + (int(255 * ca),))
    # name + tagline
    na = appear(t, 1.1, 0.6)
    if na > 0:
        text_c(d, (cx, 980), "APEX TRADE BOT", font(76), T0 + (int(255 * na),))
    ta = appear(t, 1.5, 0.6)
    if ta > 0:
        text_c(d, (cx, 1070), "AI that trades while you sleep", font(40, False), ACC2 + (int(255 * ta),))
    # bottom hairline + url
    ua = appear(t, 1.9, 0.6)
    if ua > 0:
        text_c(d, (cx, H - 120), "aicashsystem.space", monof(34), T1 + (int(255 * ua),))
    return np.array(img.convert("RGB"))


# ═══════════════════════════════════════════════════════════════════════════
# SCENE 2 — Live trading dashboard (animated chart + P&L counter)
# ═══════════════════════════════════════════════════════════════════════════
def scene_dashboard(t, dur):
    img = new_frame()
    d = ImageDraw.Draw(img, "RGBA")

    # header
    logo(d, 120, 110, 0.6)
    text_c(d, (210, 150), "Live Dashboard", font(40), T0, "lm")
    # status dot
    pulse = 0.5 + 0.5 * math.sin(t * 6)
    d.ellipse([W - 250, 138, W - 230, 158], fill=UP + (int(180 + 70 * pulse),))
    text_c(d, (W - 215, 148), "LIVE", monof(30), UP, "lm")

    # ── chart card ──
    cx0, cy0, cx1, cy1 = 70, 240, W - 70, 1020
    rrect(d, [cx0, cy0, cx1, cy1], 28, fill=PANEL + (235,), outline=(255, 255, 255, 22), width=2)
    # chart plot area
    px0, py0, px1, py1 = cx0 + 40, cy0 + 120, cx1 - 40, cy1 - 60
    lows = min(c[2] for c in CANDLES)
    highs = max(c[1] for c in CANDLES)
    rng = highs - lows or 1

    def yv(v):
        return py1 - (v - lows) / rng * (py1 - py0)
    n = len(CANDLES)
    cw = (px1 - px0) / n
    shown = ease_out(t / 2.6) * n   # candles reveal progressively
    closes_pts = []
    for i, (o, hi, lo, c) in enumerate(CANDLES):
        if i > shown:
            break
        grow = clamp(shown - i)
        xc = px0 + (i + 0.5) * cw
        up = c >= o
        col = UP if up else DOWN
        # wick
        d.line([(xc, yv(hi)), (xc, yv(lo))], fill=col + (int(200 * grow),), width=2)
        # body
        bt, bb = yv(max(o, c)), yv(min(o, c))
        bw = cw * 0.55
        body_top = bb - (bb - bt) * grow
        rrect(d, [xc - bw / 2, body_top, xc + bw / 2, bb], 3, fill=col + (int(235 * grow),))
        closes_pts.append((xc, yv(c)))
    # glowing close line
    if len(closes_pts) > 1:
        d.line(closes_pts, fill=ACC2 + (140,), width=3, joint="curve")
        lx, ly = closes_pts[-1]
        gr = 9 + 3 * math.sin(t * 5)
        d.ellipse([lx - gr, ly - gr, lx + gr, ly + gr], fill=ACC + (230,))

    # chart title + pair
    text_c(d, (px0, cy0 + 56), "BTC / USDT", font(40), T0, "lm")
    text_c(d, (px0, cy0 + 96), "AI signal: STRONG BUY", font(28, False), UP, "lm")

    # ── P&L counter card ──
    ny0 = 1060
    rrect(d, [70, ny0, W - 70, ny0 + 230], 28, fill=PANEL + (235,), outline=(255, 255, 255, 22), width=2)
    text_c(d, (110, ny0 + 50), "Today's P&L", font(34, False), T1, "lm")
    prog = ease_out(t / 3.0)
    pnl = 247.80 * prog
    text_c(d, (110, ny0 + 130), f"+${pnl:,.2f}", monof(78), UP, "lm")
    # right column: win rate
    wr = 68 * ease_out(t / 3.0)
    text_c(d, (W - 110, ny0 + 50), "Win rate", font(34, False), T1, "rm")
    text_c(d, (W - 110, ny0 + 130), f"{wr:.0f}%", monof(78), T0, "rm")

    # ── position toast sliding in ──
    if t > 2.4:
        sa = ease_out((t - 2.4) / 0.6)
        ty = 1340 + (1 - sa) * 60
        ta = int(255 * sa)
        rrect(d, [70, ty, W - 70, ty + 150], 24, fill=PANEL2 + (ta,), outline=UP + (int(120 * sa),), width=2)
        d.ellipse([110, ty + 55, 150, ty + 95], fill=UP + (int(60 * sa),))
        text_c(d, (130, ty + 75), "↑", font(40), UP + (ta,), "mm")
        text_c(d, (185, ty + 55), "Position opened", font(34), T0 + (ta,), "lm")
        text_c(d, (185, ty + 100), "BUY · 0.42 BTC · entry $61,240", monof(26), T1 + (ta,), "lm")

    # caption
    cap = appear(t, 1.0, 0.6)
    if cap > 0:
        text_c(d, (W // 2, 1620), "Real exchange. Real trades.", font(46), T0 + (int(255 * cap),))
        text_c(d, (W // 2, 1690), "Your account. Your keys.", font(46), ACC2 + (int(255 * cap),))
    return np.array(img.convert("RGB"))


# ═══════════════════════════════════════════════════════════════════════════
# SCENE 3 — Telegram control (phone mockup + chat bubbles)
# ═══════════════════════════════════════════════════════════════════════════
def scene_telegram(t, dur):
    img = new_frame()
    d = ImageDraw.Draw(img, "RGBA")
    text_c(d, (W // 2, 150), "Control it from Telegram", font(52), T0)

    # phone frame
    pw, ph = 760, 1380
    px = (W - pw) // 2
    py = 240
    rrect(d, [px, py, px + pw, py + ph], 60, fill=(12, 13, 18, 255), outline=(255, 255, 255, 30), width=3)
    # screen
    sx0, sy0, sx1, sy1 = px + 22, py + 26, px + pw - 22, py + ph - 26
    rrect(d, [sx0, sy0, sx1, sy1], 44, fill=(14, 17, 23, 255))
    # tg header
    rrect(d, [sx0, sy0, sx1, sy0 + 110], 44, fill=(23, 33, 43, 255))
    d.rectangle([sx0, sy0 + 70, sx1, sy0 + 110], fill=(23, 33, 43, 255))
    d.ellipse([sx0 + 30, sy0 + 28, sx0 + 84, sy0 + 82], fill=BG + (255,))
    logo(d, sx0 + 57, sy0 + 36, 0.28)
    text_c(d, (sx0 + 105, sy0 + 48), "Apex Trade Bot", font(34), T0, "lm")
    text_c(d, (sx0 + 105, sy0 + 86), "online", font(24, False), TG, "lm")

    # chat bubbles: (who, text, t_start). [g]/[r] tokens become drawn status dots.
    bubbles = [
        ("me",  "/status", 0.3),
        ("bot", "Balance:  $1,247.80\nToday:  +$247  (+24.7%)\n3 open positions  [g]", 0.9),
        ("me",  "/positions", 2.0),
        ("bot", "BTC   +5.2%   [g]\nETH   +2.8%   [g]\nSOL   −0.4%   [r]", 2.6),
        ("bot", "Auto-managing stops & take-profits", 3.7),
    ]
    y = sy0 + 150
    pad = 26
    maxw = sx1 - sx0 - 120
    bf = font(28, False)
    lh = 42

    def strip_tokens(s):
        return s.replace("  [g]", "").replace("  [r]", "").replace("[g]", "").replace("[r]", "")
    for who, txt, ts in bubbles:
        a = appear(t, ts, 0.45)
        lines = txt.split("\n")
        clean = [strip_tokens(ln) for ln in lines]
        bw = min(maxw, max(d.textlength(ln, font=bf) for ln in clean) + pad * 2 + 30)
        bh = len(lines) * lh + pad * 2 - 8
        if a > 0:
            slide = (1 - a) * 30
            yy = y + slide
            ia = int(255 * a)
            if who == "me":
                bx1 = sx1 - 40
                bx0 = bx1 - bw
                col = (44, 110, 158, ia)
            else:
                bx0 = sx0 + 40
                bx1 = bx0 + bw
                col = (33, 43, 54, ia)
            rrect(d, [bx0, yy, bx1, yy + bh], 22, fill=col)
            tcol = (255, 255, 255, ia) if who == "me" else (T0 + (ia,))
            ty = yy + pad - 4
            for raw, ln in zip(lines, clean):
                d.text((bx0 + pad, ty), ln, font=bf, fill=tcol)
                if "[g]" in raw or "[r]" in raw:
                    dotc = (UP if "[g]" in raw else DOWN) + (ia,)
                    dx = bx0 + pad + d.textlength(ln, font=bf) + 18
                    dcy = ty + lh // 2 - 4
                    d.ellipse([dx, dcy - 9, dx + 18, dcy + 9], fill=dotc)
                ty += lh
        y += bh + 24
    return np.array(img.convert("RGB"))


# ═══════════════════════════════════════════════════════════════════════════
# SCENE 4 — Deploy in 3 steps (checkmarks light up)
# ═══════════════════════════════════════════════════════════════════════════
def scene_deploy(t, dur):
    img = new_frame()
    d = ImageDraw.Draw(img, "RGBA")
    text_c(d, (W // 2, 200), "Live in 10 minutes.", font(60), T0)
    text_c(d, (W // 2, 280), "No coding. No monthly fees.", font(38, False), T1)

    steps = [
        ("1", "Paste your exchange API key", 0.4),
        ("2", "Pick your risk & strategy", 1.3),
        ("3", "Click “Save & Deploy”", 2.2),
    ]
    y = 420
    for num, label, ts in steps:
        a = appear(t, ts, 0.5)
        if a <= 0:
            y += 230
            continue
        slide = (1 - a) * 40
        yy = y + slide
        rrect(d, [80, yy, W - 80, yy + 180], 26,
              fill=PANEL + (int(235 * a),), outline=(255, 255, 255, int(26 * a)), width=2)
        # number circle
        d.ellipse([120, yy + 50, 200, yy + 130], fill=ACC + (int(235 * a),))
        text_c(d, (160, yy + 90), num, font(44), (255, 255, 255, int(255 * a)), "mm")
        text_c(d, (240, yy + 90), label, font(38), T0 + (int(255 * a),), "lm")
        # checkmark appears slightly after each step
        ca = appear(t, ts + 0.5, 0.4)
        if ca > 0:
            cxc, cyc = W - 160, yy + 90
            d.ellipse([cxc - 36, cyc - 36, cxc + 36, cyc + 36], fill=UP + (int(60 * ca),))
            # draw check
            p1 = (cxc - 18, cyc)
            p2 = (cxc - 4, cyc + 16 * ca)
            p3 = (cxc + 20, cyc - 18 * ca)
            d.line([p1, p2], fill=UP + (int(255 * ca),), width=6)
            d.line([p2, p3], fill=UP + (int(255 * ca),), width=6)
        y += 230
    # final banner
    ba = appear(t, 3.2, 0.6)
    if ba > 0:
        by = 1180
        rrect(d, [80, by, W - 80, by + 200], 28, fill=(39, 196, 106, int(40 * ba)),
              outline=UP + (int(160 * ba),), width=2)
        text_c(d, (W // 2, by + 70), "✓ BOT DEPLOYED", font(56), UP + (int(255 * ba),))
        text_c(d, (W // 2, by + 145), "Trading 24/7 on your account", font(36, False), T0 + (int(255 * ba),))
    return np.array(img.convert("RGB"))


# ═══════════════════════════════════════════════════════════════════════════
# SCENE 5 — CTA
# ═══════════════════════════════════════════════════════════════════════════
def scene_cta(t, dur):
    img = new_frame()
    d = ImageDraw.Draw(img, "RGBA")
    logo(d, W // 2, 520, 1.4)
    a = appear(t, 0.3, 0.6)
    text_c(d, (W // 2, 880), "APEX TRADE BOT", font(70), T0 + (int(255 * a),))
    a2 = appear(t, 0.7, 0.6)
    text_c(d, (W // 2, 970), "Crypto $297  ·  Forex $497", font(42, False), ACC2 + (int(255 * a2),))
    a3 = appear(t, 1.1, 0.6)
    if a3 > 0:
        # CTA pill
        bw = 620
        bx = (W - bw) // 2
        by = 1120
        pulse = 0.5 + 0.5 * math.sin(t * 4)
        rrect(d, [bx, by, bx + bw, by + 120], 60, fill=ACC + (int(255 * a3),))
        text_c(d, (W // 2, by + 60), "Get the bot →", font(50), (255, 255, 255, int(255 * a3)))
    a4 = appear(t, 1.5, 0.6)
    text_c(d, (W // 2, 1340), "aicashsystem.space", monof(40), T0 + (int(255 * a4),))
    a5 = appear(t, 1.8, 0.6)
    text_c(d, (W // 2, 1430), "Link in bio", font(34, False), T1 + (int(255 * a5),))
    return np.array(img.convert("RGB"))


# ── assemble ──────────────────────────────────────────────────────────────--
SCENES = [
    (scene_intro, 3.2),
    (scene_dashboard, 6.5),
    (scene_telegram, 6.0),
    (scene_deploy, 6.0),
    (scene_cta, 3.6),
]


def main():
    fps = 20 if "--fast" in sys.argv else FPS
    clips = []
    for fn, dur in SCENES:
        clip = VideoClip(frame_function=lambda t, fn=fn, dur=dur: fn(t, dur), duration=dur)
        clips.append(clip.with_fps(fps))
    final = concatenate_videoclips(clips, method="compose")
    out = OUT / "apex_demo.mp4"
    final.write_videofile(str(out), fps=fps, codec="libx264", audio=False,
                          preset="medium", logger="bar")
    print(f"\n✅ {out}  ({final.duration:.1f}s, {fps}fps)")


if __name__ == "__main__":
    main()
