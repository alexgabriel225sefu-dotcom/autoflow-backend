#!/usr/bin/env python3
"""What this environment can actually reach, right now.

Platform blocking changes without notice and differs by IP, so the honest
answer to "does Instagram work?" is a probe, not a table written last month.
This runs one cheap metadata request per platform — no download — and reports
what came back.

    python doctor.py [--cookies FILE]

Exit code is 0 whether platforms answer or not: a blocked platform is a fact
about the network, not a failure of this script.
"""

import argparse
import shutil
import subprocess
import sys

# One well-known public URL per platform. Metadata only, no stream.
PROBES = [
    ("YouTube", "https://www.youtube.com/watch?v=aqz-KE-bpKQ"),
    ("Vimeo", "https://vimeo.com/76979871"),
    ("Instagram", "https://www.instagram.com/reel/C8Qh5xvNqBv/"),
    ("Direct MP4",
     "https://test-videos.co.uk/vids/bigbuckbunny/mp4/h264/360/"
     "Big_Buck_Bunny_360_10s_1MB.mp4"),
]


def tools():
    print("Tools")
    ok = True
    for t, how in (("ffmpeg", "apt install ffmpeg"),
                   ("ffprobe", "ships with ffmpeg"),
                   ("yt-dlp", "pip install yt-dlp")):
        p = shutil.which(t)
        print(f"  {t:9} {p or 'MISSING — ' + how}")
        ok = ok and bool(p)
    return ok


def probe(name, url, cookies=None):
    if url.endswith(".mp4"):
        # A direct file needs no extractor; a HEAD is the whole test.
        try:
            r = subprocess.run(["curl", "-sSI", "--max-time", "25", url],
                               capture_output=True, text=True, timeout=40)
            first = (r.stdout or "").splitlines()[0] if r.stdout else ""
            return ("200" in first or "206" in first), first.strip()[:70]
        except Exception as e:
            return False, str(e)[:70]

    cmd = ["yt-dlp", "--no-warnings", "--skip-download",
           "--print", "%(title).45s", url]
    if cookies:
        cmd += ["--cookies", cookies]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=70)
    except subprocess.TimeoutExpired:
        return False, "timed out"
    out = (r.stdout or "").strip().splitlines()
    if r.returncode == 0 and out:
        return True, out[-1][:70]
    err = (r.stderr or "").strip().splitlines()
    return False, (err[-1][:110] if err else "no answer")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cookies", default=None)
    a = ap.parse_args()

    have = tools()
    print("\nReach (metadata only — nothing is downloaded)")
    if not shutil.which("yt-dlp"):
        print("  skipped: yt-dlp is not installed")
        return 0
    blocked = 0
    for name, url in PROBES:
        ok, detail = probe(name, url, a.cookies)
        print(f"  {name:11} {'OK   ' if ok else 'BLOCK'} {detail}")
        blocked += 0 if ok else 1

    print()
    if blocked and not a.cookies:
        print(f"{blocked} platform(s) refused. That is the datacenter-IP block,")
        print("not a bug here. Export cookies from a logged-in browser and")
        print("re-run with --cookies to see the difference.")
    elif blocked:
        print(f"{blocked} platform(s) still refused with cookies supplied —")
        print("check the cookie file matches the site and is not expired.")
    else:
        print("Everything answered.")
    if not have:
        print("\nSome tools are missing; see above.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
