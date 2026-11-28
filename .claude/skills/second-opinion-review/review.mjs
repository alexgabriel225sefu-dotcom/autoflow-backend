#!/usr/bin/env node
/**
 * Send a redacted diff to an OpenAI-compatible chat API for a second-opinion review.
 * Keys come from the environment only. Never log the key.
 *
 *   REVIEW_API_KEY=... REVIEW_API_BASE=https://api.openai.com/v1 REVIEW_MODEL=gpt-4.1 \
 *     node review.mjs --diff /tmp/review.diff --prompt ./review-prompt.md
 */
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
const here = dirname(fileURLToPath(import.meta.url));

function arg(flag, fallback) {
  const i = process.argv.indexOf(flag);
  return i >= 0 && process.argv[i + 1] ? process.argv[i + 1] : fallback;
}

function die(msg) {
  console.error(msg);
  process.exit(2);
}

const diffPath = arg("--diff");
const promptPath = arg("--prompt", resolve(here, "review-prompt.md"));
const focus = arg("--focus", "");
if (!diffPath) die("Usage: node review.mjs --diff <file> [--prompt review-prompt.md] [--focus text]");

const key = process.env.REVIEW_API_KEY || process.env.OPENAI_API_KEY || process.env.LITELLM_API_KEY;
if (!key) die("Set REVIEW_API_KEY (or OPENAI_API_KEY / LITELLM_API_KEY) in the environment. Do not pass a key as an argument.");

const base = (process.env.REVIEW_API_BASE || process.env.LITELLM_API_BASE || "https://api.openai.com/v1").replace(/\/$/, "");
const model = process.env.REVIEW_MODEL || "gpt-4.1";

const prompt = readFileSync(promptPath, "utf8");
const diff = readFileSync(diffPath, "utf8");

const secretLike = /(api[_-]?key|secret|token|password|authorization|whsec_|sk_live|sk_test|bearer\s+[a-z0-9._\-]+)/i;
const redacted = diff.split("\n").map((line) => {
  if (secretLike.test(line) && (line.startsWith("+") || line.startsWith("-") || line.startsWith(" "))) {
    return line.slice(0, 1) + " [redacted by review.mjs — possible secret]";
  }
  return line;
}).join("\n");

const body = {
  model,
  messages: [
    {
      role: "user",
      content: [
        prompt.trim(),
        focus ? `\nFocus area from the user:\n${focus}\n` : "",
        "\n## Redacted diff\n\n```\n",
        redacted,
        "\n```\n"
      ].join("")
    }
  ],
  temperature: 0.2
};

const res = await fetch(`${base}/chat/completions`, {
  method: "POST",
  headers: {
    "content-type": "application/json",
    authorization: `Bearer ${key}`
  },
  body: JSON.stringify(body)
});

if (!res.ok) {
  const text = await res.text();
  die(`Review API returned ${res.status}: ${text.slice(0, 500)}`);
}

const json = await res.json();
const content = json.choices?.[0]?.message?.content;
if (!content) die("Review API returned no message content.");
process.stdout.write(content.endsWith("\n") ? content : content + "\n");
