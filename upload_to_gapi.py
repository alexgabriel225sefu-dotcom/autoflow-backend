#!/usr/bin/env python3
"""Upload local MP4 files to Google Generative AI Files API and print new file IDs."""

import os, sys, time, json, requests
from pathlib import Path

def require_google_api_key():
    """The key lives in the environment, never in this file.

    GOOGLE_API_KEY is the name to set. GOOGLE_AI_API_KEY is accepted because
    existing deploy config already uses it. The value is not printed.
    """
    key = (os.environ.get("GOOGLE_API_KEY") or os.environ.get("GOOGLE_AI_API_KEY") or "").strip()
    if not key:
        raise SystemExit(
            "GOOGLE_API_KEY is not set. Export GOOGLE_API_KEY or "
            "GOOGLE_AI_API_KEY and run this script again."
        )
    return key

API_KEY = require_google_api_key()

VIDEOS = [
    ("v1", "outputs/tiktok-videos/ugc_v1.mp4"),
    ("v2", "outputs/tiktok-videos/ugc_v2.mp4"),
    ("v3", "outputs/tiktok-videos/ugc_v3.mp4"),
    ("v4", "outputs/tiktok-videos/ugc_v4.mp4"),
    ("v5", "outputs/tiktok-videos/ugc_v5.mp4"),
    ("v6", "outputs/tiktok-videos/ugc_v6.mp4"),
    ("v7", "outputs/tiktok-videos/ugc_v7.mp4"),
]


def upload_file(vid_id, filepath):
    path = Path(filepath)
    if not path.exists():
        print(f"[{vid_id}] MISSING: {filepath}")
        return None

    data = path.read_bytes()
    size = len(data)
    print(f"[{vid_id}] Uploading {size/1024/1024:.1f}MB...", flush=True)

    init_url = "https://generativelanguage.googleapis.com/upload/v1beta/files"
    init_resp = requests.post(
        init_url,
        headers={
            # Header, not a query parameter: a failed request's URL must not carry the key.
            "x-goog-api-key": API_KEY,
            "X-Goog-Upload-Protocol": "resumable",
            "X-Goog-Upload-Command": "start",
            "X-Goog-Upload-Header-Content-Length": str(size),
            "X-Goog-Upload-Header-Content-Type": "video/mp4",
            "Content-Type": "application/json",
        },
        json={"file": {"display_name": f"aicash_ugc_{vid_id}.mp4"}},
        timeout=30,
    )

    if init_resp.status_code != 200:
        print(f"[{vid_id}] Init failed: {init_resp.status_code} {init_resp.text[:200]}")
        return None

    upload_url = init_resp.headers.get("X-Goog-Upload-URL")
    if not upload_url:
        print(f"[{vid_id}] No upload URL returned")
        return None

    upload_resp = requests.post(
        upload_url,
        headers={
            "X-Goog-Upload-Command": "upload, finalize",
            "X-Goog-Upload-Offset": "0",
            "Content-Type": "video/mp4",
        },
        data=data,
        timeout=120,
    )

    if upload_resp.status_code not in (200, 201):
        print(f"[{vid_id}] Upload failed: {upload_resp.status_code} {upload_resp.text[:200]}")
        return None

    file_info = upload_resp.json()
    name = file_info.get("file", {}).get("name", "")
    file_id = name.split("/")[-1] if "/" in name else name
    state = file_info.get("file", {}).get("state", "")
    print(f"[{vid_id}] Uploaded → file ID: {file_id}  state: {state}")
    return file_id


if __name__ == "__main__":
    results = {}
    for vid_id, filepath in VIDEOS:
        fid = upload_file(vid_id, filepath)
        if fid:
            results[vid_id] = fid
        else:
            print(f"[{vid_id}] FAILED — stopping")
            break

    print("\n=== VEO_FILES map for server.js ===")
    print("const VEO_FILES = {")
    for vid_id, fid in results.items():
        print(f"  {vid_id}: '{fid}',")
    print("};")
    print(f"\nUploaded {len(results)}/7 videos")
