"""
Gemini Vision Integration for BioManual
Hybrid approach: Gemini for content extraction + PaddleOCR for layout detection
"""

import os
import logging
import cv2
from PIL import Image
from dotenv import load_dotenv
import google.generativeai as genai
import json

# Load environment variables
load_dotenv()

logger = logging.getLogger("BioManual")

class BioVisionGemini:
    """
    Pure Gemini Vision approach - uses Gemini for both layout and content extraction
    """
    def __init__(self):
        api_key = os.getenv('GEMINI_API_KEY')
        if not api_key or api_key == 'your-api-key-here':
            logger.error("❌ GEMINI_API_KEY not set in .env file!")
            logger.error("Please get your API key from: https://aistudio.google.com/app/apikey")
            raise ValueError("Gemini API Key not configured")
        
        genai.configure(api_key=api_key)
        model_name = os.getenv('GEMINI_MODEL', 'gemini-1.5-flash')
        self.model = genai.GenerativeModel(model_name)
        logger.info(f"✓ Gemini Vision Engine Ready ({model_name})")
    
    def analyze_page(self, image_path, filename_base):
        """
        Analyze entire page using Gemini Vision
        Returns: List of extracted elements with type, content, and bbox
        """
        # Use context manager to ensure file is closed
        with Image.open(image_path) as img:
            img.load()  # Load into memory so file can be closed
        
        prompt = """
        Analyze this biomedical manual page and extract ALL content in reading order.
        
        For each element, identify:
        1. **Type**: text, title, table, or figure
        2. **Content**: The actual text or description
        3. **Position**: Approximate bounding box [x1, y1, x2, y2] as percentages (0-100)
        
        Return ONLY valid JSON in this exact format:
        {
          "elements": [
            {
              "type": "title",
              "content": "extracted text here",
              "bbox": [10, 5, 90, 15]
            },
            {
              "type": "text",
              "content": "body text here",
              "bbox": [10, 20, 90, 40]
            }
          ]
        }
        
        Rules:
        - Extract ALL text, even in tables and figures
        - For tables: preserve structure with rows/columns
        - For figures: describe what the image shows
        - Use "title" for headings, "text" for paragraphs
        - Return ONLY the JSON, no markdown code blocks
        """
        
        try:
            response = self.model.generate_content([prompt, img])
            text = response.text.strip()
            
            # Clean up response (remove markdown code blocks if present)
            if "```json" in text:
                text = text.split("```json")[1].split("```")[0]
            elif "```" in text:
                text = text.split("```")[1].split("```")[0]
            
            # import json (removed, using global)
            data = json.loads(text.strip())
            
            elements = []
            for idx, elem in enumerate(data.get('elements', [])):
                elem_type = elem.get('type', 'text')
                content = elem.get('content', '')
                bbox = elem.get('bbox', [0, 0, 100, 100])
                
                # Convert percentage bbox to pixel coordinates (approximate)
                img_width, img_height = img.size
                x1 = int(bbox[0] * img_width / 100)
                y1 = int(bbox[1] * img_height / 100)
                x2 = int(bbox[2] * img_width / 100)
                y2 = int(bbox[3] * img_height / 100)
                
                elements.append({
                    "type": elem_type,
                    "bbox": [x1, y1, x2, y2],
                    "text": content,
                    "confidence": 0.95,  # Gemini is highly accurate
                    "crop_url": None,
                    "crop_local": None
                })
            
            logger.info(f"✓ Gemini extracted {len(elements)} elements")
            return elements
            
        except json.JSONDecodeError as e:
            logger.warning(f"Failed to parse Gemini JSON response: {e}")
            logger.warning(f"Raw response: {response.text[:200]}...")
            # Fallback: treat entire response as text
            return [{
                "type": "text",
                "bbox": [0, 0, 100, 100],
                "text": response.text,
                "confidence": 0.8,
                "crop_url": None,
                "crop_local": None
            }]
        except Exception as e:
            logger.error(f"Gemini API error: {e}")
            return []


class BioVisionHybrid:
    """
    Hybrid approach: PaddleOCR for layout detection + Gemini for accurate content extraction
    Best of both worlds!
    """
    def __init__(self):
        # Initialize Gemini
        api_key = os.getenv('GEMINI_API_KEY')
        if not api_key or api_key == 'your-api-key-here':
            logger.error("❌ GEMINI_API_KEY not set in .env file!")
            logger.error("Please get your API key from: https://aistudio.google.com/app/apikey")
            raise ValueError("Gemini API Key not configured")
        
        genai.configure(api_key=api_key)
        model_name = os.getenv('GEMINI_MODEL', 'gemini-1.5-flash')
        self.gemini = genai.GenerativeModel(model_name)
        
        # Initialize PaddleOCR for layout
        from paddleocr import PPStructure
        self.paddle = PPStructure(show_log=False, lang='en', enable_mkldnn=False)
        
        logger.info(f"✓ Hybrid Vision Engine Ready (Gemini {model_name} + PaddleOCR)")
    
    def scan_document(self, image_path, filename_base):
        """
        Hybrid scanning:
        1. PaddleOCR detects layout regions (precise bounding boxes)
        2. Gemini extracts accurate content from each region
        """
        original_img = cv2.imread(image_path)
        h, w, _ = original_img.shape
        
        # Step 1: Get layout from PaddleOCR
        paddle_result = self.paddle(original_img)
        
        if not paddle_result:
            logger.warning("PaddleOCR found no regions, falling back to full-page Gemini")
            return self._fallback_gemini_full_page(image_path, filename_base)
        
        # Sort top-to-bottom (reading order)
        paddle_result.sort(key=lambda x: x['bbox'][1])
        
        extracted_elements = []
        
        # Step 2: For each region, use Gemini to extract content
        for idx, region in enumerate(paddle_result):
            region.pop('img', None)  # Remove embedded image
            box = region['bbox']
            region_type = region['type']  # 'text', 'title', 'table', 'figure'
            
            # Crop region
            x1, y1, x2, y2 = box
            x1, y1, x2, y2 = max(0, x1), max(0, y1), min(w, x2), min(h, y2)
            
            if x2 <= x1 or y2 <= y1:
                continue
            
            crop_img_cv = original_img[y1:y2, x1:x2]
            crop_pil = Image.fromarray(cv2.cvtColor(crop_img_cv, cv2.COLOR_BGR2RGB))
            
            # Step 3: Use Gemini to extract text from this region
            text_content = self._extract_with_gemini(crop_pil, region_type)
            
            # Step 4: Save crop for tables/figures
            crop_url = None
            crop_local = None
            if region_type in ['figure', 'table']:
                from pathlib import Path
                output_dir = os.path.join(os.path.dirname(image_path), "..", "output_results")
                os.makedirs(output_dir, exist_ok=True)
                
                crop_fname = f"{filename_base}_{region_type}_{idx}.jpg"
                crop_local = os.path.join(output_dir, crop_fname)
                cv2.imwrite(crop_local, crop_img_cv)
                crop_url = f"http://127.0.0.1:8000/output/{crop_fname}".replace("\\", "/")
            
            extracted_elements.append({
                "type": region_type,
                "bbox": box,
                "text": text_content,
                "confidence": 0.95,  # Gemini + Paddle = high confidence
                "crop_url": crop_url,
                "crop_local": crop_local
            })
        
        logger.info(f"✓ Hybrid extracted {len(extracted_elements)} elements")
        return extracted_elements
    
    def _extract_with_gemini(self, crop_image, region_type):
        """Extract text from cropped region using Gemini"""
        try:
            if region_type in ['text', 'title']:
                prompt = "Extract all text from this image. Return only the text, no formatting or explanations."
            elif region_type == 'table':
                prompt = "This is a table. Extract all data preserving rows and columns. Format as plain text with clear structure."
            elif region_type == 'figure':
                prompt = "Describe this figure/diagram in detail. What does it show? Include any text visible in the image."
            else:
                prompt = "Extract all text from this image."
            
            response = self.gemini.generate_content([prompt, crop_image])
            return response.text.strip()
            
        except Exception as e:
            logger.warning(f"Gemini extraction failed for {region_type}: {e}")
            return f"[{region_type.upper()} - extraction failed]"
    
    def _fallback_gemini_full_page(self, image_path, filename_base):
        """Fallback to full-page Gemini analysis if PaddleOCR fails"""
        logger.info("Using full-page Gemini analysis as fallback")
        gemini_only = BioVisionGemini()
        return gemini_only.analyze_page(image_path, filename_base)


# Factory function to choose vision engine
def create_vision_engine(mode='hybrid'):
    """
    Create vision engine based on mode
    
    Args:
        mode: 'gemini' (pure Gemini) or 'hybrid' (Gemini + PaddleOCR)
    
    Returns:
        Vision engine instance
    """
    if mode == 'gemini':
        return BioVisionGemini()
    elif mode == 'hybrid':
        return BioVisionHybrid()
    else:
        raise ValueError(f"Unknown mode: {mode}. Use 'gemini' or 'hybrid'")
