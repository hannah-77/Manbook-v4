import os
import sys
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
import logging
from openrouter_client import get_openrouter_client

logging.basicConfig(level=logging.INFO)

openrouter = get_openrouter_client()
print(f"Model: {openrouter.model}")
print(f"Provider: {openrouter.provider}")

try:
    res = openrouter.call("Hello, are you there?", timeout=15)
    print(f"Res: {res}")
except Exception as e:
    print(f"Error: {e}")
