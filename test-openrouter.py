import os
import requests

api_key = os.environ["OPENROUTER_API_KEY"]

response = requests.post(
    "https://openrouter.ai/api/v1/chat/completions",
    headers={
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    },
    json={
        "model": "openrouter/free",
        "messages": [
            {
                "role": "user",
                "content": "「テスト成功」と日本語で返答してください。"
            }
        ],
    },
    timeout=60,
)

response.raise_for_status()

data = response.json()
print(data["choices"][0]["message"]["content"])
