import pytesseract
from PIL import Image
import logging

logger = logging.getLogger(__name__)

def extract_text_from_image(image_path: str) -> str:
    """
    Extracts text from an image using Tesseract OCR.
    Supports English, Russian, and Simplified Chinese.
    """
    try:
        # Load image
        img = Image.open(image_path)
        
        # We specify multiple languages: eng (English), rus (Russian), chi_sim (Simplified Chinese)
        text = pytesseract.image_to_string(img, lang="eng+rus+chi_sim")
        return text.strip()
    except Exception as e:
        logger.error(f"OCR failed for {image_path}: {e}")
        return ""
