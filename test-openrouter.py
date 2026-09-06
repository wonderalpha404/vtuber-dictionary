import os
import sys
import requests
import json

# This script performs a single test call to OpenRouter's chat completions endpoint.
# Requirements:
# - OPENROUTER_API_KEY must be set in the environment (do NOT print it)
# - Uses the free-model router identifier: "openrouter/free"
# - Makes exactly one request and prints a concise success or error message

API_KEY = os.getenv("OPENROUTER_API_KEY")
if not API_KEY:
    print("ERROR: OPENROUTER_API_KEY is not set in the environment (check GitHub Secrets). Aborting.")
    sys.exit(1)

URL = "https://openrouter.ai/api/v1/chat/completions"

payload = {
    "model": "openrouter/free",
    "messages": [
        {"role": "user", "content": "「テスト成功」と日本語で返答してください。"}
    ],
    "max_tokens": 200,
    "temperature": 0.2,
}

headers = {
    "Authorization": f"Bearer {API_KEY}",
    "Content-Type": "application/json",
}

try:
    resp = requests.post(URL, headers=headers, json=payload, timeout=60)
except requests.RequestException as e:
    print(f"ERROR: Network error when contacting OpenRouter: {e}")
    sys.exit(2)

# If status is not OK, show a safe error message (do not print secrets)
if resp.status_code != 200:
    safe_msg = None
    try:
        err = resp.json()
        # Prefer human-readable fields if present
        if isinstance(err, dict):
            safe_msg = err.get("error") or err.get("message") or json.dumps({k: v for k, v in err.items() if k != 'api_key'}, ensure_ascii=False)
        else:
            safe_msg = str(err)
    except Exception:
        safe_msg = resp.text[:1000]
    print(f"ERROR: OpenRouter API returned HTTP {resp.status_code}: {safe_msg}")
    sys.exit(3)

# Parse JSON
try:
    data = resp.json()
except Exception as e:
    print(f"ERROR: Received non-JSON response from OpenRouter: {e}")
    sys.exit(4)

# Extract assistant content from common locations in the response
assistant_text = None
if isinstance(data, dict):
    choices = data.get("choices")
    if isinstance(choices, list) and choices:
        first = choices[0]
        if isinstance(first, dict):
            # OpenAI-style: {"message": {"role":..., "content": "..."}}
            msg = first.get("message")
            if isinstance(msg, dict):
                assistant_text = msg.get("content") or msg.get("text")
            # Some providers put text directly
            if not assistant_text:
                assistant_text = first.get("text") or first.get("content")
    # Some responses might include a top-level 'output' or 'message'
    if not assistant_text:
        if isinstance(data.get("message"), str):
            assistant_text = data.get("message")
        elif data.get("output"):
            assistant_text = data.get("output")

if not assistant_text:
    # Could not find assistant text; print safe diagnostics (keys and truncated JSON)
    keys = list(data.keys()) if isinstance(data, dict) else []
    print("ERROR: Could not locate assistant content in the API response.")
    print("Response top-level keys:", keys[:20])
    print("Truncated response (first 2000 chars):")
    try:
        print(json.dumps(data, ensure_ascii=False)[:2000])
    except Exception:
        print(str(data)[:2000])
    sys.exit(5)

# Success: print a clear success message and the assistant response (safe)
print("OpenRouter test succeeded. Assistant response below:")
print(assistant_text.strip())
sys.exit(0)
