
import os
import google.generativeai as genai
from dotenv import load_dotenv

load_dotenv()

api_key = os.getenv("GEMINI_API_KEY")
print(f"Gemini API Key found: {api_key[:5]}...{api_key[-4:] if api_key else 'None'}")

if not api_key:
    print("❌ No GEMINI_API_KEY found in .env")
    exit(1)

try:
    genai.configure(api_key=api_key)
    
    print("Checking available models...")
    found_models = []
    for m in genai.list_models():
        if 'generateContent' in m.supported_generation_methods:
            print(f"- {m.name}")
            found_models.append(m.name)
            
    print(f"\nFound {len(found_models)} text-generation models.")
            
    # Try 1.5 Flash which has 1500 RPD free limit (vs 20 for Pro/Newer models)
    model_name = 'gemini-2.5-flash'
    print(f"\nTesting connection with {model_name} (High Limit Model)...")
    model = genai.GenerativeModel(model_name)
    response = model.generate_content("Say 'Gemini 2.5 Flash is Working'")
    
    print("Response:", response.text)
    print("✅ Direct Gemini API is CONNECTED.")

except Exception as e:
    print(f"❌ Connection Failed: {e}")
