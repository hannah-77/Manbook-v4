import os
import requests
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
AI_MODELS = os.getenv("AI_MODEL", "").split(",")

print(f"🔑 OpenRouter API Key: {OPENROUTER_API_KEY[:5]}...{OPENROUTER_API_KEY[-4:] if OPENROUTER_API_KEY else 'None'}")
print(f"🤖 Configured Models: {AI_MODELS}")

if not OPENROUTER_API_KEY:
    print("❌ No OPENROUTER_API_KEY found in .env")
    exit(1)

url = "https://openrouter.ai/api/v1/chat/completions"
headers = {
    "Authorization": f"Bearer {OPENROUTER_API_KEY}",
    "Content-Type": "application/json",
    "HTTP-Referer": "http://localhost:8000",
    "X-Title": "BioManual Test"
}

for model in AI_MODELS:
    model = model.strip()
    if not model: continue
    
    print(f"\nTesting Model: {model}...")
    data = {
        "model": model,
        "messages": [
            {"role": "user", "content": "Say 'OpenRouter Connected'"}
        ]
    }
    
    try:
        response = requests.post(url, headers=headers, json=data, timeout=10)
        if response.status_code == 200:
            result = response.json()
            content = result['choices'][0]['message']['content']
            print(f"✅ Success! Response: {content}")
        else:
            print(f"❌ Failed (Status {response.status_code}): {response.text}")
    except Exception as e:
        print(f"❌ Error: {e}")
