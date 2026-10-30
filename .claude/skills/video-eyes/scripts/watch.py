#!/usr/bin/env python3
"""Turn a video into things Claude can actually look at and read.

One file, stdlib plus yt-dlp and ffmpeg. No API key, no account, no service.

    python watch.py <url-or-file> [--frames N] [--every S] [--cookies FILE]

Writes into an output directory and prints a manifest: the frame paths to read
as images, the transcript path if subtitles existed, and — when a fetch fails —
the reason, in the platform's own words rather than a summary of it.

WHY THE FAILURE PATH GETS AS MUCH CARE AS THE SUCCESS PATH

Every large platform now blocks datacenter IPs. A tool that returns "could not
fetch" is useless for deciding what to do next, because "the link is private",
"YouTube wants a login from this IP" and "the network is down" need three
different responses from a person. So the exact stderr is kept and classified,
and the classification says what would fix it.
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys

# Frames are downscaled before Claude reads them. Vision does not benefit from
# a 4K still, and a smaller file is a faster read.
_FRAME_WIDTH = 720
_MAX_FRAMES = 24


def _run(cmd, timeout=600):
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return p.returncode, p.stdout, p.stderr
    except subprocess.TimeoutExpired:
        return 124, "", f"timed out after {timeout}s"
    except FileNotFoundError as e:
        return 127, "", str(e)


def _need(tool):
    if not shutil.which(tool):
        sys.exit(f"{tool} is not installed. "
                 + ("pip install yt-dlp" if tool == "yt-dlp"
                    else "install ffmpeg"))


def classify(stderr):
    """(reason, what_would_fix_it). The whole point of this script's honesty.

    Kept as ordered patterns rather than a dict lookup because the messages
    overlap — a private Instagram post and a rate-limited one both mention the
    login wall, and the first match is the more specific one.
    """
    s = (stderr or "").lower()
    checks = [
        ("sign in to confirm you", "the platform wants a signed-in session",
         "export cookies from a browser where you are logged in, and pass "
         "--cookies. There is no flag that replaces this from a datacenter IP."),
        ("only works when logged-in", "this platform requires a login",
         "pass --cookies from a logged-in browser session"),
        ("private", "the post is private", "nothing here can fix that"),
        ("empty media response", "the platform returned nothing for this post",
         "usually a login wall or a deleted post; try --cookies"),
        ("unavailable", "the media is unavailable",
         "check the link is still live"),
        ("no video could be found", "the link has no video on it",
         "check you copied the right URL"),
        ("http error 429", "rate limited",
         "wait, then retry with --sleep-interval"),
        ("requested format is not available",
         "no stream matched the format filter",
         "the platform published no downloadable format at this quality — "
         "often the same login wall wearing a different message"),
        ("unsupported url", "yt-dlp does not know this site",
         "download the file yourself and pass the path instead"),
        ("timed out", "the fetch timed out", "retry, or check the network"),
    ]
    for needle, reason, fix in checks:
        if needle in s:
            return reason, fix
    return "the fetch failed", (stderr or "").strip()[:300]


def fetch(target, outdir, cookies=None, section=None):
    """(path, meta, error). A local file is used as-is; a URL is downloaded."""
    if os.path.isfile(target):
        return target, {"source": "local file", "title": os.path.basename(target)}, None

    _need("yt-dlp")
    base = os.path.join(outdir, "video")
    cmd = ["yt-dlp", "--no-warnings", "--no-playlist",
           # Smallest usable stream, with a real fallback chain. Frames are
           # downscaled anyway, so a 4K download to make 720px stills wastes
           # bandwidth. `worst[height>=240]` alone FAILS outright when no
           # format matches the filter — the last `/best` is what turns that
           # from an error into a larger download.
           "-f", "worst[height>=240]/worst[ext=mp4]/worst/best",
           "-o", base + ".%(ext)s",
           "--write-info-json",
           # Subtitles are the cheapest and richest signal a video has. Both
           # kinds: uploaded ones are accurate, auto ones are usually present.
           "--write-auto-sub", "--write-sub", "--sub-lang", "en.*,ro.*",
           "--sub-format", "vtt/srt/best"]
    if cookies:
        cmd += ["--cookies", cookies]
    if section:
        cmd += ["--download-sections", f"*{section}", "--force-keyframes-at-cuts"]
    cmd.append(target)

    rc, _out, err = _run(cmd, timeout=900)
    video = next((os.path.join(outdir, f) for f in sorted(os.listdir(outdir))
                  if f.startswith("video.") and not f.endswith(
                      (".json", ".vtt", ".srt", ".part"))), None)
    if rc != 0 or not video:
        reason, fix = classify(err)
        return None, {}, {"reason": reason, "fix": fix,
                          "raw": (err or "").strip()[-600:]}

    meta = {}
    info = os.path.join(outdir, "video.info.json")
    if os.path.isfile(info):
        try:
            with open(info, encoding="utf-8") as f:
                j = json.load(f)
            meta = {"title": j.get("title"), "uploader": j.get("uploader"),
                    "duration": j.get("duration"), "url": j.get("webpage_url"),
                    "description": (j.get("description") or "")[:1500]}
        except Exception:
            pass
    return video, meta, None


def frames(video, outdir, count, every=None):
    """Extract stills. Returns the paths, in order.

    `every` seconds when given; otherwise `count` frames spread across the
    whole video, which is what you want when you have not seen it yet.
    """
    _need("ffmpeg")
    count = max(1, min(int(count), _MAX_FRAMES))
    rc, dur_s, _ = _run(["ffprobe", "-v", "error", "-show_entries",
                         "format=duration", "-of", "csv=p=0", video], 60)
    try:
        duration = float((dur_s or "0").strip())
    except ValueError:
        duration = 0.0

    vf = (f"fps=1/{float(every)}" if every
          else f"fps={count}/{max(duration, 1):.4f}" if duration
          else "fps=1/5")
    pattern = os.path.join(outdir, "frame_%03d.jpg")
    rc, _o, err = _run(["ffmpeg", "-loglevel", "error", "-i", video,
                        "-vf", f"{vf},scale={_FRAME_WIDTH}:-2",
                        "-frames:v", str(count), "-q:v", "3",
                        pattern, "-y"], 600)
    got = sorted(os.path.join(outdir, f) for f in os.listdir(outdir)
                 if re.fullmatch(r"frame_\d{3}\.jpg", f))
    return got, duration, (err.strip()[:300] if rc != 0 else "")


def transcript(outdir):
    """The subtitle file as plain text, or None. Never invents one."""
    sub = next((os.path.join(outdir, f) for f in sorted(os.listdir(outdir))
                if f.endswith((".vtt", ".srt"))), None)
    if not sub:
        return None, None
    try:
        with open(sub, encoding="utf-8", errors="replace") as f:
            raw = f.read()
    except Exception:
        return None, None
    lines, seen = [], set()
    for ln in raw.splitlines():
        ln = ln.strip()
        if (not ln or ln.startswith(("WEBVTT", "Kind:", "Language:"))
                or "-->" in ln or ln.isdigit()):
            continue
        ln = re.sub(r"<[^>]+>", "", ln)
        # Auto-captions repeat each line as the rolling window advances.
        if ln and ln not in seen:
            seen.add(ln)
            lines.append(ln)
    text = "\n".join(lines)
    path = os.path.join(outdir, "transcript.txt")
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    return path, len(lines)


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("target", help="a URL, or a path to a video file")
    ap.add_argument("--out", default=None, help="output directory")
    ap.add_argument("--frames", type=int, default=8)
    ap.add_argument("--every", type=float, default=None,
                    help="one frame every N seconds instead of N total")
    ap.add_argument("--cookies", default=None,
                    help="cookies.txt from a logged-in browser")
    ap.add_argument("--section", default=None,
                    help="only this range, e.g. 30-90")
    a = ap.parse_args()

    outdir = a.out or os.path.join("/tmp", "video-eyes",
                                   re.sub(r"\W+", "_", a.target)[-60:] or "clip")
    os.makedirs(outdir, exist_ok=True)

    video, meta, err = fetch(a.target, outdir, a.cookies, a.section)
    if err:
        print(json.dumps({"ok": False, **err, "target": a.target}, indent=2))
        return 1

    imgs, duration, ferr = frames(video, outdir, a.frames, a.every)
    tpath, tlines = transcript(outdir)

    print(json.dumps({
        "ok": True,
        "video": video,
        "durationS": round(duration, 1),
        "meta": meta,
        "frames": imgs,
        "frameError": ferr or None,
        "transcript": tpath,
        "transcriptLines": tlines,
        # Said plainly so the caller does not have to infer it: no transcript
        # means the platform published none, not that the audio was silent.
        "note": ("no subtitles were published for this video"
                 if not tpath else None),
    }, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
