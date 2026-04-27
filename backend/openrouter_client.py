"""
OpenRouter Client - Manbook-v4
1 model, 1 provider, allow_fallbacks=False (strict).

Konfigurasi di .env:
  OPENROUTER_API_KEY = sk-or-v1-...
  AI_MODEL           = deepseek/deepseek-r1
  AI_PROVIDER        = deepinfra/fp4
  AI_ALLOW_FALLBACKS = false
"""

import os
import time
import logging
import requests
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger("OpenRouterClient")

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
OPENROUTER_URL     = "https://openrouter.ai/api/v1/chat/completions"

AI_MODEL           = os.getenv("AI_MODEL") or os.getenv("AI_VISION_MODEL") or "google/gemini-2.0-flash-001"
AI_PROVIDER        = os.getenv("AI_PROVIDER", "")  # Empty = auto-select
AI_ALLOW_FALLBACKS = os.getenv("AI_ALLOW_FALLBACKS", "false").strip().lower() in ("true", "1", "yes")


class OpenRouterClient:
    def __init__(self):
        self.api_key         = OPENROUTER_API_KEY
        self.model           = AI_MODEL
        self.provider        = AI_PROVIDER
        self.allow_fallbacks = AI_ALLOW_FALLBACKS
        self.is_available    = bool(self.api_key)

        if self.is_available:
            logger.info(f"✓ OpenRouterClient Ready | Model: {self.model} | Provider: {self.provider}")
        else:
            logger.warning("⚠️  OPENROUTER_API_KEY tidak ditemukan di .env")

    def call(self, prompt, image_base64=None, timeout=30):
        if not self.is_available:
            return None

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "HTTP-Referer":  "http://localhost:8000",
            "X-Title":       "Manbook-v4 BioManual",
            "Content-Type":  "application/json",
        }

        # Multi-modal support
        if image_base64:
            message_content = [
                {"type": "text", "text": prompt},
                {
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:image/jpeg;base64,{image_base64}"
                    }
                }
            ]
        else:
            message_content = prompt

        payload = {
            "model":    self.model,
            "messages": [{"role": "user", "content": message_content}],
        }
        # Only force a specific provider when explicitly set.
        # For vision/image calls, we need auto-routing to find a compatible endpoint.
        if self.provider:
            payload["provider"] = {
                "order":           [self.provider],
                "allow_fallbacks": self.allow_fallbacks,
            }


        for attempt in range(3):
            try:
                response = requests.post(OPENROUTER_URL, headers=headers, json=payload, timeout=timeout)

                if response.status_code == 429:
                    wait = 2 ** (attempt + 1)
                    if attempt < 2:
                        logger.warning(f"⏳ Rate limit. Retry dalam {wait}s...")
                        time.sleep(wait)
                        continue
                    return None

                if response.status_code != 200:
                    logger.warning(f"⚠️  HTTP {response.status_code}: {response.text[:150]}")
                    return None

                data = response.json()
                if "choices" not in data or not data["choices"]:
                    logger.warning("⚠️  Response kosong dari API")
                    return None

                content = data["choices"][0]["message"]["content"].strip()
                usage   = data.get("usage", {})
                logger.info(f"✅ Tokens: {usage.get('prompt_tokens','?')}→{usage.get('completion_tokens','?')}")
                return content

            except requests.exceptions.Timeout:
                logger.warning(f"⏱️  Timeout setelah {timeout}s")
                return None
            except Exception as e:
                logger.warning(f"❌ Error: {e}")
                return None

        return None

    def test_connection(self):
        print(f"\n{'='*50}")
        print(f"  Model   : {self.model}")
        print(f"  Provider: {self.provider}")
        print(f"  Fallback: {self.allow_fallbacks}")
        print(f"{'='*50}")
        print(f"  Testing...", end="", flush=True)

        result = self.call("Reply with exactly: 'OpenRouter OK'", timeout=15)
        if result:
            print(f"✅  {result[:60]}")
            return True
        print("❌  Gagal. Cek API key, model, dan provider di .env")
        return False


_client = None

def get_openrouter_client():
    global _client
    if _client is None:
        _client = OpenRouterClient()
    return _client


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(message)s")
    get_openrouter_client().test_connection()
