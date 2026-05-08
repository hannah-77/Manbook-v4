import cv2
import numpy as np
from paddleocr import PaddleOCR
import logging

logging.basicConfig(level=logging.INFO)

print("Initializing PaddleOCR...")
ocr = PaddleOCR(use_angle_cls=False, lang='en', use_gpu=False, show_log=True)

# Create a dummy image with text
img = np.zeros((100, 400, 3), dtype=np.uint8) + 255
cv2.putText(img, "TEST PADDLE OCR", (50, 60), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 0), 2)
cv2.imwrite("test_paddle.png", img)

print("Running OCR...")
result = ocr.ocr("test_paddle.png", cls=False)
print(f"Result: {result}")
