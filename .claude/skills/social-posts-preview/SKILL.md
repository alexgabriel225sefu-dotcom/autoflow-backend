---
name: social-posts-preview
description: Show how a social post will look on LinkedIn, X, Instagram, TikTok, Reels, Shorts, Threads, or Facebook by filling a local HTML preview. Use whenever you write or adapt a social post for Apex4Traders or the user asks to preview a caption.
---

# Social post previews

Adapted from the OpenMausBot `social-posts` skill (Apache-2.0). The card markup in `posts.html` is adapted from MiniMock (MIT, Copyright (c) 2026 Tushar Bhardwaj) and Lucide icons (ISC). Keep the licence comment at the top of `posts.html` if you copy or edit it.

In Claude Code there is no `show_html` tool. Preview by writing a local folder and opening it in a browser.

## Apex safety (mandatory)

- Copy: no profit, income, win-rate, or "make money" claims; no fake discounts or "was" prices; do not mention Telegram in Apex marketing.
- "MT4/MT5 coming soon" only when that feature is in the post. Licence price, if stated, is $497. Affiliate share, if stated, is 30% (~$149).
- Prefer demo language ("test it on demo", "no real money required to try"). Do not show real-looking account numbers or balances in screenshots.
- This skill previews posts. It does not publish them. Never post to a live account unless the user explicitly asks and a sanctioned posting path exists.
- Do not include secrets, private customer names, or unreleased credentials in a preview you might screenshot.

## Fill the template

1. Copy `posts.html` from this skill folder into a working directory (for example `preview/index.html`).
2. Replace only the JSON inside the `posts-data` script block. Keep the rest of the file, including the licence notice.
3. Put local images or video posters next to it and name them in `src` / `poster`.
4. Serve the folder and open it:

```sh
python3 -m http.server 4173 --directory preview
# then open http://127.0.0.1:4173/
```

Opening the file directly with `file://` is fine for text-only posts. Use the local server when media must load.

```json
{
  "account": { "name": "Apex4Traders", "handle": "apex4traders", "subtitle": "Automated trading for cTrader", "avatar": "avatar.png" },
  "posts": [{
    "title": "Demo launch",
    "when": "Draft",
    "text": "Default text for platforms that have none of their own.",
    "media": [{ "src": "photo.jpg", "alt": "Product UI on demo" }],
    "platforms": {
      "linkedin": { "text": "Its own caption." },
      "x": {},
      "tiktok": {}
    }
  }]
}
```

- `platforms` chooses which cards render: `instagram`, `linkedin`, `x`, `threads`, `facebook`, `tiktok`, `reels`, `shorts`. Each may have its own `text`, `media`, and `when`; anything omitted falls back to the post.
- Several entries in `posts` stack on one page.
- With no `avatar`, the card shows initials. Media items: `{ "src", "alt" }` for an image, or `{ "video", "poster", "duration" }` (seconds) for a video. Add `width` and `height` when the file size cannot be read.

## Carousels without images

You can draft slides in JSON. `"slideShape"` is `"4:5"` (default) or `"1:1"`.

```json
"brand": { "background": "#0A0B0D", "text": "#F5F7FA", "accent": "#22E07A" },
"media": [
  { "layout": "cover", "kicker": "Apex4Traders", "title": "Your rules. Your max loss.", "note": "Swipe" },
  { "layout": "points", "title": "Before you start", "points": ["See max loss first", "Risk Guard on demo", "Every decision journaled"] },
  { "layout": "quote", "quote": "Test it free on a demo.", "by": "apex4traders.com" }
]
```

One idea per slide, 5–10 slides, about 20 words a slide, last slide is the CTA. These slides are a preview only; exporting real images or a LinkedIn PDF is a separate step — say so.

## Platform limits

From each platform's public docs. The cards may note these; nothing is blocked here.

| Platform | Text | Media |
|---|---|---|
| Instagram | 2,200 characters, 30 hashtags | Images 4:5 to 1.91:1. Carousel up to 20; slides crop to the first shape |
| LinkedIn | 3,000 characters; hook in the first 150 to avoid a cut | A "carousel" is usually a PDF |
| X | 280 (emoji and CJK count as 2, any link as 23) | Up to 4 photos, or 1 video |
| Threads | 500 | Carousel 2 to 20 |
| Facebook | No published limit this skill checks | |
| TikTok | Caption 2,200 | Up to 35 photos |
| Reels | As Instagram | 9:16 recommended |
| Shorts | | Square or vertical; up to 3 minutes |

The preview is a close likeness, not a pixel-perfect match. Say so if asked.
