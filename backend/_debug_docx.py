import sys
import os

backend_path = r"C:\Users\Hanna\Manbook-v4\backend"
if backend_path not in sys.path:
    sys.path.insert(0, backend_path)

from direct_reader import extract_docx_direct

file_path = r"C:\Hanna Kuliah\Magang\45. rev04 - MBENG_Fox Baby.docx"
try:
    results = extract_docx_direct(file_path, 'id')
    print("Found elements:", len(results))
    if len(results) == 0:
        print("No elements found!")
except Exception as e:
    print("Error:", e)
