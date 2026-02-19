import os
import requests
import json
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

MODAL_API_KEY = os.getenv("MODAL_API_KEY")

print(f"🔑 Modal API Key: {MODAL_API_KEY[:5]}...{MODAL_API_KEY[-4:] if MODAL_API_KEY else 'None'}")

if not MODAL_API_KEY:
    print("❌ No MODAL_API_KEY found in .env")
    print("Please add your key to .env: MODAL_API_KEY=your_token_here")
    exit(1)

url = "https://api.us-west-2.modal.direct/v1/chat/completions"
headers = {
    "Content-Type": "application/json",
    "Authorization": f"Bearer {MODAL_API_KEY}"
}

data = {
    "model": "zai-org/GLM-5-FP8",
    "messages": [
        {"role": "user", "content": "How many r-s are in strawberry?"}
    ],
    "max_tokens": 500
}

print(f"\nSending request to {url}...")
print(f"Model: {data['model']}")
print(f"Prompt: {data['messages'][0]['content']}")

try:
    response = requests.post(url, headers=headers, json=data, timeout=120)
    
    if response.status_code == 200:
        result = response.json()
        print("\n✅ Success!")
        print("-" * 50)
        print(json.dumps(result, indent=2))
        print("-" * 50)
        
        if 'choices' in result and len(result['choices']) > 0:
            content = result['choices'][0]['message']['content']
            print(f"\nResponse Content:\n{content}")
    else:
        print(f"\n❌ Failed (Status {response.status_code})")
        print(response.text)

except Exception as e:
    print(f"\n❌ Loop Error: {e}")
