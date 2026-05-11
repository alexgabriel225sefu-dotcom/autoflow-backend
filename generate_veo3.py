#!/usr/bin/env python3
"""
AI Cash Systems - Veo 3 UGC Video Generator
Generates realistic talking-head TikTok videos via Google Veo 3 API.
"""

import os, time, requests
from pathlib import Path
from google import genai
from google.genai import types

API_KEY = os.environ.get("GOOGLE_AI_API_KEY", "AIzaSyDmRhfKfQ8e9t6ACH9XXJWNkjA1lzhFVPU")
client = genai.Client(api_key=API_KEY)

OUTPUT_DIR = Path("outputs/tiktok-videos")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# UGC prompt template — persoana reala, selfie style, vorbeste la camera
UGC_TEMPLATE = """
A young person in their late 20s filming themselves with a phone camera, casual selfie style,
sitting at a desk or on a couch, speaking directly and authentically to camera.
Natural lighting from a window. Wearing a plain t-shirt or hoodie.
They say: "{speech}"
Authentic, raw, emotional UGC style. Vertical 9:16 format. No filters, real and relatable.
"""

SCRIPTS = [
    {
        "id": "v1",
        "speech": (
            "I made three hundred dollars selling AI bots. "
            "I don't even know how to code. "
            "I found a course called AI Cash Systems. "
            "Two hours to build a bot — a business paid four hundred dollars for it. "
            "The course is thirty seven dollars. I made that back in week one. "
            "Link in bio if you actually want to learn this."
        ),
    },
    {
        "id": "v2",
        "speech": (
            "Nobody talks about how exhausting it is to work hard and still not have enough. "
            "I started asking a different question — not how do I work harder, "
            "but what skill pays me differently? "
            "AI automation was my answer. First client in thirty days. "
            "You don't need to quit your job tomorrow. "
            "You need one skill that gives you options."
        ),
    },
    {
        "id": "v3",
        "speech": (
            "I tried dropshipping. Lost four hundred dollars. "
            "I tried affiliate marketing. Made zero. "
            "I almost gave up entirely. "
            "What changed was finding a skill with actual demand. "
            "Businesses need AI automation right now. "
            "They're paying freelancers three hundred, five hundred, eight hundred dollars "
            "for things you can learn to build in a weekend. "
            "I'm not a success story yet. I'm someone who finally found the right direction. "
            "Come figure it out with me."
        ),
    },
]


def generate_video(script):
    vid_id = script["id"]
    prompt = UGC_TEMPLATE.format(speech=script["speech"])

    print(f"\n[{vid_id}] Generating with Veo 3...")
    print(f"[{vid_id}] Prompt length: {len(prompt)} chars")

    try:
        operation = client.models.generate_video(
            model="veo-3.0-generate-preview",
            prompt=prompt,
            config=types.GenerateVideoConfig(
                aspect_ratio="9:16",
                duration_seconds=8,
                number_of_videos=1,
            ),
        )

        print(f"[{vid_id}] Waiting for generation (can take 2-5 min)...")
        while not operation.done:
            time.sleep(10)
            operation = client.operations.get(operation)
            print(f"[{vid_id}] Still generating...")

        if operation.response and operation.response.generated_videos:
            video = operation.response.generated_videos[0]
            out_path = OUTPUT_DIR / f"ugc_{vid_id}.mp4"

            # Download video
            video_data = client.files.download(file=video.video)
            with open(out_path, "wb") as f:
                f.write(video_data)

            print(f"[{vid_id}] Saved → {out_path}")
            return ("OK", vid_id, str(out_path))
        else:
            err = str(operation.error) if operation.error else "No video returned"
            return ("ERR", vid_id, err)

    except Exception as e:
        return ("ERR", vid_id, str(e))


if __name__ == "__main__":
    print("=== AI Cash Systems — Veo 3 UGC Generator ===")
    print(f"API Key: {API_KEY[:20]}...")
    print(f"Output: {OUTPUT_DIR.resolve()}")

    results = []
    for script in SCRIPTS:
        status, vid_id, info = generate_video(script)
        results.append((status, vid_id, info))
        if status == "ERR":
            print(f"\n[{vid_id}] ERROR: {info}")
            print("Opresc — verifica eroarea inainte de a continua.")
            break

    print("\n=== REZULTATE ===")
    for status, vid_id, info in results:
        icon = "OK" if status == "OK" else "FAIL"
        print(f"  [{icon}] {vid_id}: {info}")
