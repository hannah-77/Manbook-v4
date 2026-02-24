"""
check_openrouter.py — Test koneksi OpenRouter
Jalankan ini untuk memastikan API key, model, dan provider berfungsi.

Cara pakai:
  python check_openrouter.py
"""
import logging
logging.basicConfig(level=logging.WARNING)

from openrouter_client import get_openrouter_client

if __name__ == "__main__":
    client = get_openrouter_client()

    if not client.is_available:
        print("\n❌ OPENROUTER_API_KEY tidak ditemukan di .env!")
        exit(1)

    key_preview = client.api_key[:10] + "..." + client.api_key[-4:]
    print(f"\n🔑 API Key : {key_preview}")
    print(f"🤖 Model   : {client.model}")
    print(f"🏭 Provider: {client.provider}")
    print(f"↩  Fallback: {client.allow_fallbacks}")

    client.test_connection()
