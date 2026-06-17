#!/usr/bin/env python3
"""Apex Trade Bot — cinematic 16:9 brand commercial (local, no paid API).

A logo-driven commercial: candlesticks stream in and resolve into the Apex
logo, the bars rise with an overshoot bounce, a light-sweep shine crosses the
mark, the name types in, then the product story (live chart, stats, deploy) and
a closing CTA. Landscape 1920×1080, built frame-by-frame.

Run:
    python scripts/make_bot_commercial.py          # full 30fps
    python scripts/make_bot_commercial.py --fast    # 20fps preview
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

W, H = 1920, 1080
BG   = (6, 6, 8)
PANEL = (17, 17, 21)
ACC  = (255, 45, 79)
ACC2 = (255, 92, 116)
UP   = (39, 196, 106)
DOWN = (255, 45, 79)
T0   = (245, 245, 247)
T1   = (150, 150, 160)
FPS  = 30


# ── easing ───────────────────────────────────────────────────────────────────
def clamp(x, a=0.0, b=1.0):
    return max(a, min(b, x))


def ease_out(x):
    x = clamp(x)
    return 1 - (1 - x) ** 3


def ease_out_back(x):
    x = clamp(x)
    c1 = 1.70158
    c3 = c1 + 1
    return 1 + c3 * (x - 1) ** 3 + c1 * (x - 1) ** 2


def appear(t, start, dur=0.5, ease=ease_out):
    return ease((t - start) / dur) if t > start else 0.0


# ── fonts ──────────────────────────────────────────────────────────────────--
_FC = {}


def font(size, bold=True):
    key = (size, bold)
    if key not in _FC:
        name = "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf"
        p = f"/usr/share/fonts/truetype/dejavu/{name}"
        _FC[key] = ImageFont.truetype(p, size) if os.path.exists(p) else ImageFont.load_default()
    return _FC[key]


def monof(size):
    key = ("m", size)
    if key not in _FC:
        p = "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf"
        _FC[key] = ImageFont.truetype(p, size) if os.path.exists(p) else font(size)
    return _FC[key]


# ── background (built once) ──────────────────────────────────────────────────
def build_bg():
    img = Image.new("RGBA", (W, H), BG + (255,))
    glow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow)
    gd.ellipse([W * 0.18, H * -0.2, W * 0.82, H * 0.9], fill=(255, 45, 79, 40))
    glow = glow.filter(ImageFilter.GaussianBlur(220))
    img.alpha_composite(glow)
    d = ImageDraw.Draw(img, "RGBA")
    for x in range(0, W, 80):
        d.line([(x, 0), (x, H)], fill=(255, 255, 255, 6), width=1)
    for y in range(0, H, 80):
        d.line([(0, y), (W, y)], fill=(255, 255, 255, 6), width=1)
    return img


_BG = build_bg()


def frame():
    return _BG.copy()


def rrect(d, box, r, **kw):
    d.rounded_rectangle(box, radius=r, **kw)


def tc(d, xy, s, f, fill, anchor="mm"):
    d.text(xy, s, font=f, fill=fill, anchor=anchor)


# ── logo geometry ─────────────────────────────────────────────────────────────
# bars: (dx, dy, w, h, alpha) relative to (cx, top); scale multiplies all.
LOGO_BARS = [(-150, 120, 58, 150, 120), (-50, 60, 58, 210, 188), (50, 0, 58, 270, 255)]
CIRCLE = (80, -12, 34)  # dx, dy(top of tallest), r at scale 1


def draw_logo_full(d, cx, top, scale=1.0, alpha=255):
    def s(v):
        return v * scale
    for (dx, dy, w, h, a) in LOGO_BARS:
        x0, y0 = cx + s(dx), top + s(dy)
        rrect(d, [x0, y0, x0 + s(w), y0 + s(h)], s(28),
              fill=ACC + (int(a * alpha / 255),))
    cdx, cdy, cr = CIRCLE
    cxr, cyr, r = cx + s(cdx), top + s(cdy), s(cr)
    d.ellipse([cxr - r, cyr - r, cxr + r, cyr + r], fill=ACC2 + (alpha,))


def logo_alpha_mask(cx, top, scale):
    """Numpy alpha mask (H,W) of the full logo — for the shine sweep."""
    layer = Image.new("L", (W, H), 0)
    d = ImageDraw.Draw(layer)

    def s(v):
        return v * scale
    for (dx, dy, w, h, a) in LOGO_BARS:
        x0, y0 = cx + s(dx), top + s(dy)
        d.rounded_rectangle([x0, y0, x0 + s(w), y0 + s(h)], radius=s(28), fill=a)
    cdx, cdy, cr = CIRCLE
    cxr, cyr, r = cx + s(cdx), top + s(cdy), s(cr)
    d.ellipse([cxr - r, cyr - r, cxr + r, cyr + r], fill=255)
    return np.asarray(layer, dtype=np.float32) / 255.0


# precompute hero-logo mask (scene A) once
_HERO_CX, _HERO_TOP, _HERO_SCALE = W // 2, 300, 1.0
_HERO_MASK = logo_alpha_mask(_HERO_CX, _HERO_TOP, _HERO_SCALE)
_XX = np.tile(np.arange(W, dtype=np.float32), (H, 1))
_YY = np.tile(np.arange(H, dtype=np.float32).reshape(-1, 1), (1, W))


def apply_shine(img, center_x, strength):
    """Additive diagonal light band over the logo, masked by the logo alpha."""
    if strength <= 0:
        return img
    # diagonal band: distance from line x - 0.4*y = center_x
    proj = _XX - 0.45 * _YY
    band = np.exp(-((proj - center_x) ** 2) / (2 * 130.0 ** 2))
    add = (band * _HERO_MASK * 255 * strength).astype(np.uint8)
    arr = np.asarray(img.convert("RGB"), dtype=np.uint16)
    arr[..., 0] = np.minimum(255, arr[..., 0] + add)
    arr[..., 1] = np.minimum(255, arr[..., 1] + add)
    arr[..., 2] = np.minimum(255, arr[..., 2] + add)
    return Image.fromarray(arr.astype(np.uint8)).convert("RGBA")


# ── price series for chart ─────────────────────────────────────────────────--
def price_series(n=46, seed=11):
    s = [seed]

    def rnd():
        s[0] = (s[0] * 1103515245 + 12345) % 2 ** 31
        return s[0] / 2 ** 31
    out, p, drift = [], 100.0, 0.0
    for i in range(n):
        if i % 7 == 0:
            drift = (rnd() - 0.32) * 1.2
        o = p
        p = max(60, o + drift + (rnd() - 0.5) * 2.4)
        out.append((o, max(o, p) + rnd() * 1.3, min(o, p) - rnd() * 1.3, p))
    return out


CANDLES = price_series()


# ═══════════════════════════════════════════════════════════════════════════
# SCENE A — Logo reveal (the hero moment)
# ═══════════════════════════════════════════════════════════════════════════
def scene_logo(t, dur):
    img = frame()
    d = ImageDraw.Draw(img, "RGBA")
    cx, top, sc = _HERO_CX, _HERO_TOP, _HERO_SCALE

    # 0.0-1.2: faint candlesticks stream in along the baseline
    base_y = top + 320
    n = 26
    cw = 46
    x0 = cx - n * cw / 2
    reveal = ease_out(t / 1.0) * n
    for i in range(n):
        if i > reveal:
            break
        fade = clamp(reveal - i) * (0.25 + 0.0 * i)
        o, hi, lo, c = CANDLES[i]
        col = UP if c >= o else DOWN
        xc = x0 + i * cw
        h = (c - 60) * 1.1
        yb = base_y
        yt = base_y - h * 0.35
        a = int(70 * fade)
        d.line([(xc, yt - 18), (xc, yt + 18)], fill=col + (a,), width=2)
        rrect(d, [xc - 8, min(yt, yb), xc + 8, max(yt, yb)], 3, fill=col + (a,))

    # 0.3-1.5: bars rise with overshoot bounce, staggered
    for idx, (dx, dy, w, h, a) in enumerate(LOGO_BARS):
        delay = 0.3 + idx * 0.18
        g = appear(t, delay, 0.7, ease_out_back)
        if g <= 0:
            continue
        x0b, full_h = cx + dx * sc, h * sc
        gh = full_h * g
        y_bottom = top + (dy + h) * sc
        rrect(d, [x0b, y_bottom - gh, x0b + w * sc, y_bottom], 28 * sc, fill=ACC + (a,))
    # circle pop
    cg = appear(t, 0.95, 0.5, ease_out_back)
    if cg > 0:
        cdx, cdy, cr = CIRCLE
        cxr, cyr, r = cx + cdx * sc, top + cdy * sc, cr * sc * cg
        d.ellipse([cxr - r, cyr - r, cxr + r, cyr + r], fill=ACC2 + (255,))

    # 1.4-2.4: light sweep shine across the logo
    if 1.35 < t < 2.5:
        sp = (t - 1.35) / 1.0
        center = -200 + sp * (W + 400)
        strength = math.sin(clamp(sp) * math.pi) * 0.9
        img = apply_shine(img, center, strength)
        d = ImageDraw.Draw(img, "RGBA")

    # name reveal via left-to-right mask wipe
    na = appear(t, 1.7, 0.8)
    if na > 0:
        name = "APEX TRADE BOT"
        nf = font(120)
        full_w = d.textlength(name, font=nf)
        nx = cx - full_w / 2
        ny = top + 470
        # clip width grows
        clip_w = int(full_w * na)
        txt_layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        td = ImageDraw.Draw(txt_layer)
        td.text((nx, ny), name, font=nf, fill=T0 + (255,))
        mask = Image.new("L", (W, H), 0)
        ImageDraw.Draw(mask).rectangle([0, 0, int(nx) + clip_w, H], fill=255)
        img.paste(txt_layer, (0, 0), Image.composite(txt_layer.split()[3], mask.point(lambda v: 0), mask))
        d = ImageDraw.Draw(img, "RGBA")

    # tagline
    ta = appear(t, 2.4, 0.6)
    if ta > 0:
        tc(d, (cx, top + 640), "AI that trades while you sleep", font(54, False), ACC2 + (int(255 * ta),))
    return np.array(img.convert("RGB"))


# ═══════════════════════════════════════════════════════════════════════════
# SCENE B — Stat counters
# ═══════════════════════════════════════════════════════════════════════════
def scene_stats(t, dur):
    img = frame()
    d = ImageDraw.Draw(img, "RGBA")
    draw_logo_full(d, 150, 70, 0.32)
    tc(d, (250, 110), "APEX TRADE BOT", font(40), T0, "lm")

    tc(d, (W // 2, 250), "Built to run 24/7.", font(78), T0)
    p = ease_out(t / 1.6)
    stats = [
        (f"{p*8:.0f}", "exchanges supported"),
        (f"{68*p:.0f}%", "avg win rate (paper)"),
        ("24/7", "fully automated"),
    ]
    cw = W // 3
    for i, (big, small) in enumerate(stats):
        a = appear(t, 0.3 + i * 0.2, 0.6)
        if a <= 0:
            continue
        cx = cw * i + cw // 2
        if big == "24/7":
            big = "24/7" if t > 0.9 else ""
        tc(d, (cx, 560), big, monof(130), ACC2 + (int(255 * a),))
        tc(d, (cx, 680), small, font(40, False), T1 + (int(255 * a),))
    ca = appear(t, 1.4, 0.6)
    if ca > 0:
        tc(d, (W // 2, 880), "Your exchange. Your keys. Your money.", font(48), T0 + (int(255 * ca),))
    return np.array(img.convert("RGB"))


# ═══════════════════════════════════════════════════════════════════════════
# SCENE C — Split: message + live chart
# ═══════════════════════════════════════════════════════════════════════════
def scene_chart(t, dur):
    img = frame()
    d = ImageDraw.Draw(img, "RGBA")
    # left text
    la = appear(t, 0.2, 0.7)
    if la > 0:
        ia = int(255 * la)
        tc(d, (110, 380), "Real AI.", font(96), T0 + (ia,), "lm")
        tc(d, (110, 480), "Real exchange.", font(96), ACC2 + (ia,), "lm")
        tc(d, (110, 600), "Analyzes the market and", font(44, False), T1 + (ia,), "lm")
        tc(d, (110, 655), "executes trades on autopilot.", font(44, False), T1 + (ia,), "lm")

    # right chart card
    cx0, cy0, cx1, cy1 = 1000, 220, W - 90, H - 220
    rrect(d, [cx0, cy0, cx1, cy1], 30, fill=PANEL + (235,), outline=(255, 255, 255, 24), width=2)
    tc(d, (cx0 + 40, cy0 + 55), "BTC / USDT", font(48), T0, "lm")
    tc(d, (cx0 + 40, cy0 + 110), "AI signal: STRONG BUY", font(32, False), UP, "lm")
    px0, py0, px1, py1 = cx0 + 40, cy0 + 170, cx1 - 40, cy1 - 50
    lows = min(c[2] for c in CANDLES)
    highs = max(c[1] for c in CANDLES)
    rng = highs - lows or 1

    def yv(v):
        return py1 - (v - lows) / rng * (py1 - py0)
    n = len(CANDLES)
    cw = (px1 - px0) / n
    shown = ease_out(t / 2.2) * n
    pts = []
    for i, (o, hi, lo, c) in enumerate(CANDLES):
        if i > shown:
            break
        grow = clamp(shown - i)
        xc = px0 + (i + 0.5) * cw
        col = UP if c >= o else DOWN
        d.line([(xc, yv(hi)), (xc, yv(lo))], fill=col + (int(200 * grow),), width=2)
        bt, bb = yv(max(o, c)), yv(min(o, c))
        bw = cw * 0.55
        rrect(d, [xc - bw / 2, bb - (bb - bt) * grow, xc + bw / 2, bb], 3, fill=col + (int(235 * grow),))
        pts.append((xc, yv(c)))
    if len(pts) > 1:
        d.line(pts, fill=ACC2 + (150,), width=3, joint="curve")
        lx, ly = pts[-1]
        gr = 10 + 3 * math.sin(t * 5)
        d.ellipse([lx - gr, ly - gr, lx + gr, ly + gr], fill=ACC + (235,))
    return np.array(img.convert("RGB"))


# ═══════════════════════════════════════════════════════════════════════════
# SCENE D — Deploy in 3 steps (horizontal)
# ═══════════════════════════════════════════════════════════════════════════
def scene_deploy(t, dur):
    img = frame()
    d = ImageDraw.Draw(img, "RGBA")
    tc(d, (W // 2, 180), "Live in 10 minutes.", font(84), T0)
    tc(d, (W // 2, 270), "No coding. No monthly fees.", font(44, False), T1)
    steps = [("1", "Paste API key", 0.3), ("2", "Set your risk", 0.8), ("3", "Click Deploy", 1.3)]
    cw = W // 3
    for i, (num, label, ts) in enumerate(steps):
        a = appear(t, ts, 0.6, ease_out_back)
        if a <= 0:
            continue
        cx = cw * i + cw // 2
        scale = a
        bw, bh = 440 * scale, 300 * scale
        rrect(d, [cx - bw / 2, 430, cx + bw / 2, 430 + bh], 28,
              fill=PANEL + (int(235 * clamp(a)),), outline=(255, 255, 255, int(24 * clamp(a))), width=2)
        if a > 0.6:
            d.ellipse([cx - 45, 480, cx + 45, 570], fill=ACC + (255,))
            tc(d, (cx, 525), num, font(54), (255, 255, 255, 255))
            tc(d, (cx, 650), label, font(46), T0)
            ca = appear(t, ts + 0.5, 0.4)
            if ca > 0:
                cyc = 710
                d.line([(cx - 22, cyc), (cx - 6, cyc + 18 * ca)], fill=UP + (int(255 * ca),), width=7)
                d.line([(cx - 6, cyc + 18 * ca), (cx + 26, cyc - 22 * ca)], fill=UP + (int(255 * ca),), width=7)
    ba = appear(t, 2.0, 0.6)
    if ba > 0:
        tc(d, (W // 2, 940), "✓  Trading 24/7 on your account", font(56), UP + (int(255 * ba),))
    return np.array(img.convert("RGB"))


# ═══════════════════════════════════════════════════════════════════════════
# SCENE E — CTA close
# ═══════════════════════════════════════════════════════════════════════════
def scene_cta(t, dur):
    img = frame()
    # gentle zoom-in on logo via scale
    sc = 0.9 + 0.12 * ease_out(t / 1.5)
    d = ImageDraw.Draw(img, "RGBA")
    draw_logo_full(d, W // 2, int(180 + (1 - ease_out(t / 1.2)) * 20), sc)
    # shine pass on the CTA logo
    a = appear(t, 0.4, 0.6)
    tc(d, (W // 2, 600), "APEX TRADE BOT", font(96), T0 + (int(255 * a),))
    a2 = appear(t, 0.8, 0.6)
    tc(d, (W // 2, 710), "Crypto  $297      Forex  $497", font(52, False), ACC2 + (int(255 * a2),))
    a3 = appear(t, 1.2, 0.6)
    if a3 > 0:
        bw = 560
        bx = (W - bw) // 2
        rrect(d, [bx, 800, bx + bw, 905], 52, fill=ACC + (int(255 * a3),))
        tc(d, (W // 2, 852), "Get the bot →", font(52), (255, 255, 255, int(255 * a3)))
    a4 = appear(t, 1.6, 0.6)
    tc(d, (W // 2, 985), "aicashsystem.space", monof(46), T0 + (int(255 * a4),))
    return np.array(img.convert("RGB"))


SCENES = [
    (scene_logo, 3.6),
    (scene_stats, 3.4),
    (scene_chart, 3.6),
    (scene_deploy, 3.6),
    (scene_cta, 3.4),
]


def main():
    fps = 20 if "--fast" in sys.argv else FPS
    clips = []
    for fn, dur in SCENES:
        clip = VideoClip(frame_function=lambda t, fn=fn, dur=dur: fn(t, dur), duration=dur)
        clips.append(clip.with_fps(fps))
    final = concatenate_videoclips(clips, method="compose")
    out = OUT / "apex_commercial.mp4"
    final.write_videofile(str(out), fps=fps, codec="libx264", audio=False,
                          preset="medium", logger="bar")
    print(f"\n✅ {out}  ({final.duration:.1f}s, {fps}fps, {W}x{H})")


if __name__ == "__main__":
    main()
