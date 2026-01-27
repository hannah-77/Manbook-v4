"""
Quick test script to verify Gemini integration
"""

import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

print("=" * 50)
print("  Gemini Integration Test")
print("=" * 50)
print()

# Test 1: Check API Key
api_key = os.getenv('GEMINI_API_KEY')
if not api_key:
    print("❌ GEMINI_API_KEY not found in .env")
    print("   Please add your API key to backend/.env")
    exit(1)
elif api_key == 'your-api-key-here':
    print("❌ GEMINI_API_KEY not configured")
    print("   Please replace 'your-api-key-here' with your actual API key")
    print()
    print("   Get your API key from:")
    print("   https://aistudio.google.com/app/apikey")
    exit(1)
else:
    print(f"✅ API Key found: {api_key[:10]}...")

# Test 2: Check Vision Mode
vision_mode = os.getenv('VISION_MODE', 'hybrid')
print(f"✅ Vision Mode: {vision_mode}")

# Test 3: Try importing Gemini
try:
    import google.generativeai as genai
    print("✅ google-generativeai imported successfully")
except ImportError as e:
    print(f"❌ Failed to import google-generativeai: {e}")
    exit(1)

# Test 4: Try configuring Gemini
try:
    genai.configure(api_key=api_key)
    print("✅ Gemini API configured")
except Exception as e:
    print(f"❌ Failed to configure Gemini: {e}")
    exit(1)

# Test 5: Try creating model
try:
    model_name = os.getenv('GEMINI_MODEL', 'gemini-1.5-flash')
    model = genai.GenerativeModel(model_name)
    print(f"✅ Gemini model created: {model_name}")
except Exception as e:
    print(f"❌ Failed to create model: {e}")
    exit(1)

# Test 6: Try a simple API call
try:
    print()
    print("Testing API call...")
    response = model.generate_content("Say 'Hello from Gemini!'")
    print(f"✅ API Response: {response.text}")
except Exception as e:
    print(f"❌ API call failed: {e}")
    print()
    print("Possible reasons:")
    print("- Invalid API key")
    print("- No internet connection")
    print("- API quota exceeded")
    exit(1)

# Test 7: Try importing custom module
try:
    from gemini_vision import create_vision_engine
    print("✅ gemini_vision module imported successfully")
except ImportError as e:
    print(f"❌ Failed to import gemini_vision: {e}")
    exit(1)

print()
print("=" * 50)
print("  🎉 All Tests Passed!")
print("=" * 50)
print()
print("Your Gemini integration is ready to use!")
print()
print("Next steps:")
print("1. Start backend: python main.py")
print("2. Upload a PDF to test the hybrid vision mode")
print("3. Compare results with old PaddleOCR-only version")
