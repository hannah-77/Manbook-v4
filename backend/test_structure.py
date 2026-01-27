import os
import cv2
from paddleocr import PPStructure, save_structure_res

try:
    # Initialize PPStructure
    table_engine = PPStructure(show_log=True, lang='en')
    print("PPStructure initialized successfully")
except Exception as e:
    print(f"Error initializing PPStructure: {e}")
