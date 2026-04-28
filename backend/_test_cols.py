import fitz
import cv2
import numpy as np
import os
import sys

def test_split():
    pdf_path = "SPIROMETERSP10W.pdf"
    if not os.path.exists(pdf_path):
        print("File not found")
        return
        
    doc = fitz.open(pdf_path)
    # Test on page 3 (index 2) which probably has 4 columns
    page = doc.load_page(3)
    pix = page.get_pixmap(dpi=150)
    img_data = pix.tobytes("png")
    
    nparr = np.frombuffer(img_data, np.uint8)
    img_cv = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
    
    from image_processing import split_columns_simple
    cv2.imwrite("test_page.png", img_cv)
    res = split_columns_simple("test_page.png", "test", ".")
    print("split_columns_simple returned:", res)

if __name__ == "__main__":
    test_split()
