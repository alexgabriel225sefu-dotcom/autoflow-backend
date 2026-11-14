---
name: video-eyes
description: Watch and analyse a video — frames Claude can actually see, plus the published transcript. Works on YouTube, Instagram, TikTok, X, Vimeo, Facebook and ~1800 other sites through yt-dlp, and on any local file. Entirely free — no API key, no account, no paid service. Use when the user shares a video URL or file and wants it described, summarised, analysed, transcribed, or compared; when they ask what happens in a video; or when they want ad creative, a reel, or a clip broken down.
---

# Video eyes

Turn a video into things that can actually be looked at.

    python .claude/skills/video-eyes/scripts/watch.py <url-or-file> [options]

It prints a JSON manifest. Read the frame paths with the Read tool — those are
images and they render visually. Read the transcript path as text.

## What is proven to work

Measured in this environment, not assumed:

| | |
|---|---|
| Frame extraction from any local file | ✅ works |
| Reading those frames as images | ✅ works — this is the "eyes" |
| Direct video URLs over HTTPS | ✅ works |
| Published subtitles → transcript | ✅ works when the platform has them |
| Metadata from YouTube (title, channel, duration) | ✅ works |
| **Downloading the video stream from YouTube** | ❌ blocked from this IP |
| Instagram, TikTok, Vimeo, X | ❌ blocked from this IP |

## The one real limitation, and the free fix

Every large platform now blocks datacenter IP ranges. The message differs —
"Sign in to confirm you're not a bot", "only works when logged-in", "empty
media response" — but the cause is the same, and there is **no flag that
replaces a session**. Forcing the `android` or `ios` player client gets
metadata through and does not get the stream through.

The fix is free and takes a minute, once:

1. Install a cookies.txt extension in the browser where you are logged in
   (Get cookies.txt LOCALLY, or similar).
2. Export cookies for the site — youtube.com, instagram.com, whichever.
3. Save the file somewhere the session can read, e.g. `/tmp/cookies.txt`.
4. Pass `--cookies /tmp/cookies.txt`.

Everything above then works, including Instagram reels and YouTube video.

**Do not commit a cookies file.** It is a live session for that account —
anyone with it is logged in as you. Keep it outside the repo.

## Options

| Flag | Meaning |
|---|---|
| `--frames N` | how many stills, spread across the whole video (default 8, max 24) |
| `--every S` | one still every S seconds instead of N total |
| `--section 30-90` | only that range — much faster on a long video |
| `--cookies FILE` | a cookies.txt from a logged-in browser |
| `--out DIR` | where to write (default under `/tmp/video-eyes/`) |

## How to actually use it

**A short clip or reel** — 8 frames across the whole thing is usually enough
to describe what happens:

    python .claude/skills/video-eyes/scripts/watch.py "<url>" --frames 8

**A long video** — take a section rather than the whole file:

    python .claude/skills/video-eyes/scripts/watch.py "<url>" --section 120-180 --every 5

**Ad creative analysis** — the first three seconds carry the hook, so sample
them densely:

    python .claude/skills/video-eyes/scripts/watch.py "<url>" --section 0-6 --every 0.5

Then read every frame path in the manifest. Describe what is actually in them;
do not infer content from the title.

## When a fetch fails

The manifest carries `reason` and `fix`, and `raw` with the platform's own
words. Report the reason rather than "it did not work" — "the post is private"
and "YouTube wants a login from this IP" need different responses from a
person, and only one of them is fixable.

## What this does NOT do

- **No audio transcription.** It reads subtitles the platform already
  published. If there are none, the manifest says so explicitly rather than
  leaving it ambiguous. Whisper would add it and would also add a model
  download and a lot of CPU; that has not been done.
- **No login, no scraping around a paywall.** If content requires a session,
  it requires your session — supplied deliberately as cookies.
- **It reports absence as absence.** No transcript means none was published,
  never that the video was silent.

## Requirements

`ffmpeg` (present) and `yt-dlp` (`pip install yt-dlp`). Both free and
open-source. Run `scripts/doctor.py` to check the environment and see which
platforms currently answer.
