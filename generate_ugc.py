#!/usr/bin/env python3
import os, json, time, requests, base64, datetime

API_KEY = os.environ.get("GOOGLE_AI_API_KEY", "")
BASE_URL = "https://generativelanguage.googleapis.com/v1beta"
MODEL = "veo-3.1-generate-preview"
OUTPUT_DIR = "outputs/ugc-ads"
LOG_FILE = "logs/veo-generations.jsonl"

PROMPT = (
    "UGC selfie-style vertical video, shot on iPhone, handheld shaky authentic feel. "
    "Young adult, mid-20s, casual outfit (hoodie or t-shirt), sitting at a desk or couch at home, "
    "natural daylight from a window. Looks straight into camera, candid and relatable expression. "
    "Speaks naturally with genuine excitement: "
    "'Bro. I made $300 with AI and I don't even know how to code. "
    "I found this course — AI Cash Systems — spent two hours building my first automation bot for a local business.' "
    "Then a brief silent beat scrolling through a laptop course dashboard and nodding. "
    "Then continues: 'It's $37. I made that back in week one. Link in bio if you actually want to learn this.' "
    "Authentic, no background music, natural room sounds only. "
    "TikTok/Instagram Reels aesthetic, 9:16 aspect ratio."
)

os.makedirs(OUTPUT_DIR, exist_ok=True)
os.makedirs("logs", exist_ok=True)


def start_generation(variation_num):
    url = f"{BASE_URL}/models/{MODEL}:predictLongRunning?key={API_KEY}"
    body = {
        "instances": [{"prompt": PROMPT}],
        "parameters": {
            "aspectRatio": "9:16",
            "durationSeconds": 8,
            "sampleCount": 1,
            "personGeneration": "allow_adult",
        },
    }
    resp = requests.post(url, json=body, timeout=60)
    resp.raise_for_status()
    op = resp.json()
    op_name = op.get("name", "")
    print(f"[V{variation_num}] Operation started: {op_name}")
    return op_name


def poll_operation(op_name, variation_num, max_wait=300):
    url = f"{BASE_URL}/{op_name}?key={API_KEY}"
    start = time.time()
    interval = 10
    while time.time() - start < max_wait:
        resp = requests.get(url, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        if data.get("done"):
            return data
        elapsed = int(time.time() - start)
        print(f"[V{variation_num}] Waiting... {elapsed}s elapsed")
        time.sleep(interval)
    raise TimeoutError(f"V{variation_num}: timed out after {max_wait}s")


def save_video(result, variation_num):
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"{OUTPUT_DIR}/ugc_v{variation_num}_{timestamp}.mp4"

    response = result.get("response", {})
    predictions = response.get("predictions", [])

    if not predictions:
        print(f"[V{variation_num}] No predictions in response: {json.dumps(result, indent=2)[:500]}")
        return None

    pred = predictions[0]
    video_data = pred.get("bytesBase64Encoded") or pred.get("video", {}).get("bytesBase64Encoded")
    video_uri = pred.get("videoUri") or pred.get("video", {}).get("uri")

    if video_data:
        with open(filename, "wb") as f:
            f.write(base64.b64decode(video_data))
        print(f"[V{variation_num}] Saved: {filename}")
        return filename
    elif video_uri:
        video_resp = requests.get(video_uri, timeout=60)
        video_resp.raise_for_status()
        with open(filename, "wb") as f:
            f.write(video_resp.content)
        print(f"[V{variation_num}] Downloaded from URI: {filename}")
        return filename
    else:
        print(f"[V{variation_num}] Unexpected response format: {json.dumps(pred, indent=2)[:500]}")
        return None


def log_result(variation_num, op_name, filename, status, error=None):
    entry = {
        "timestamp": datetime.datetime.now().isoformat(),
        "variation": variation_num,
        "model": MODEL,
        "operation": op_name,
        "status": status,
        "outputFile": filename,
        "error": error,
        "prompt_words": len(PROMPT.split()),
        "aspectRatio": "9:16",
        "durationSeconds": 8,
    }
    with open(LOG_FILE, "a") as f:
        f.write(json.dumps(entry) + "\n")


if __name__ == "__main__":
    import threading

    NUM_VARIATIONS = 2
    results = {}

    def run_variation(n):
        try:
            op_name = start_generation(n)
            result = poll_operation(op_name, n)
            if "error" in result:
                err = result["error"]
                print(f"[V{n}] API error: {err}")
                log_result(n, op_name, None, "failed", str(err))
                results[n] = {"status": "failed", "error": str(err)}
            else:
                filename = save_video(result, n)
                log_result(n, op_name, filename, "generated")
                results[n] = {"status": "generated", "file": filename}
        except Exception as e:
            print(f"[V{n}] Exception: {e}")
            log_result(n, "unknown", None, "failed", str(e))
            results[n] = {"status": "failed", "error": str(e)}

    threads = [threading.Thread(target=run_variation, args=(i + 1,)) for i in range(NUM_VARIATIONS)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    print("\n=== RESULTS ===")
    for n, r in results.items():
        print(f"  Variation {n}: {r}")
