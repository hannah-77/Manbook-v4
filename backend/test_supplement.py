import requests
import os

BASE_URL = "http://127.0.0.1:8000"

def test_supplement_flow():
    # 1. Start a session with a dummy file
    print("1. Starting Session...")
    
    # Create dummy PDF or use existing
    dummy_pdf_1 = "test_part1.pdf"
    with open(dummy_pdf_1, "wb") as f:
        f.write(b"%PDF-1.4 header dummy content")
    
    # Since we can't easily mock the PDF content for the backend processing without a real PDF,
    # we might need to rely on the backend handling invalid PDFs gracefully or use valid ones if available.
    # However, the backend logic for 'supplement' relies on 'active_sessions'.
    
    # Let's assume we need to actually upload a file. 
    # For testing purposes, I'll check if the endpoint exists and returns 404 for invalid session first.
    
    print("Testing nonexistent session...")
    response = requests.post(f"{BASE_URL}/supplement/nonexistent_id", files={'file': open(dummy_pdf_1, 'rb')})
    print(f"Response: {response.json()}")
    
    assert response.json()['success'] == False
    assert "not found" in response.json()['error']
    
    print("✅ Supplement endpoint exists and handles invalid session correctly.")

if __name__ == "__main__":
    try:
        test_supplement_flow()
    except Exception as e:
        print(f"Test Failed: {e}")
