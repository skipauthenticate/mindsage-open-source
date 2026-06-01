"""Image PII detection and redaction using OCR + Presidio.

Provides on-device image PII protection for MindSage. Detects PII text
in images using OCR (EasyOCR primary, Tesseract fallback) and redacts
by applying color fill or blur over detected regions.

Memory footprint:
    - EasyOCR (GPU): ~600-900MB VRAM, ~150MB CPU
    - EasyOCR (CPU): ~600-800MB CPU (Mac/no CUDA)
    - Tesseract (CPU): ~35MB

Configuration:
    IMAGE_PII_ENABLED: Enable/disable image PII redaction (default: true)
    IMAGE_PII_OCR_ENGINE: OCR engine - "easyocr" or "tesseract" (default: easyocr)
    IMAGE_REDACTION_COLOR: Redaction fill color (default: black)
    IMAGE_PII_USE_BLUR: Use blur instead of solid fill (default: false)
    IMAGE_PII_BLUR_RADIUS: Blur radius in pixels (default: 15)
    IMAGE_PII_PADDING: Extra pixels around detected regions (default: 5)
"""

import gc
import os
import time
import hashlib
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, TYPE_CHECKING

# PIL for image manipulation
try:
    from PIL import Image, ImageDraw, ImageFilter
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False
    Image = None
    ImageDraw = None
    ImageFilter = None

# EasyOCR - primary OCR engine (GPU-accelerated)
try:
    import easyocr
    EASYOCR_AVAILABLE = True
except ImportError:
    EASYOCR_AVAILABLE = False
    easyocr = None

# Tesseract - fallback OCR engine (CPU-only)
try:
    import pytesseract
    TESSERACT_AVAILABLE = True
except ImportError:
    TESSERACT_AVAILABLE = False
    pytesseract = None

# PyTorch for GPU detection
try:
    import torch
    TORCH_AVAILABLE = True
except ImportError:
    TORCH_AVAILABLE = False
    torch = None

# Type checking imports
if TYPE_CHECKING:
    from .pii_protection import PIIProtector
    from .model_manager import ModelManager, ModelType


class OCREngine(Enum):
    """Supported OCR engines."""
    EASYOCR = "easyocr"
    TESSERACT = "tesseract"


@dataclass
class OCRBox:
    """A single OCR detection with bounding box."""
    text: str
    x: int
    y: int
    width: int
    height: int
    confidence: float

    def calculate_pii_bbox(
        self,
        pii_start: int,
        pii_end: int,
        buffer_ratio: float = 0.3,
        redact_full_box: bool = True,
    ) -> Tuple[int, int, int, int]:
        """Calculate bounding box for PII substring within this OCR box.

        By default (redact_full_box=True), returns the entire OCR box for
        reliable coverage. This is the recommended setting because:
        - Proportional fonts have variable character widths
        - OCR bounding boxes may not align perfectly with characters
        - It's better to over-redact than to leave PII visible

        When redact_full_box=False, uses proportional character positioning
        to estimate where the PII text appears (less reliable).

        Args:
            pii_start: Start character index of PII in self.text
            pii_end: End character index of PII in self.text
            buffer_ratio: Extra buffer as ratio of avg character width (default 0.3)
            redact_full_box: If True, redact entire OCR box (recommended)

        Returns:
            Tuple of (x, y, width, height) for the PII region
        """
        text_len = len(self.text)
        if text_len == 0:
            return self.x, self.y, self.width, self.height

        # Recommended: redact the entire OCR box when PII is found
        # This ensures complete coverage regardless of font metrics
        if redact_full_box:
            return self.x, self.y, self.width, self.height

        # Legacy: proportional positioning (less reliable with proportional fonts)
        # Calculate proportional position within the text
        # Assuming roughly uniform character width (approximation)
        start_ratio = pii_start / text_len
        end_ratio = pii_end / text_len

        # Map to pixel coordinates
        pii_x = self.x + int(self.width * start_ratio)
        pii_width = int(self.width * (end_ratio - start_ratio))

        # Add buffer to ensure coverage (character widths vary in proportional fonts)
        avg_char_width = self.width / text_len if text_len > 0 else 0
        buffer = int(avg_char_width * buffer_ratio)

        # Apply buffer, ensuring we stay within original box bounds
        pii_x = max(self.x, pii_x - buffer)
        pii_end_x = min(self.x + self.width, pii_x + pii_width + 2 * buffer)
        pii_width = pii_end_x - pii_x

        return pii_x, self.y, pii_width, self.height


@dataclass
class OCRResult:
    """Result from OCR processing."""
    text: str  # Full extracted text
    boxes: List[OCRBox]  # Individual detections with positions
    engine: str  # Which OCR engine was used
    processing_time_ms: float


@dataclass
class ImagePIIRegion:
    """A detected PII region in an image."""
    x: int
    y: int
    width: int
    height: int
    pii_type: str  # PERSON, EMAIL_ADDRESS, etc.
    original_text: str
    confidence: float


@dataclass
class RedactionResult:
    """Result from image PII redaction."""
    redacted_image_path: str
    original_image_path: Optional[str]
    regions_redacted: List[ImagePIIRegion]
    session_id: Optional[str]
    processing_time_ms: float
    ocr_engine: str


def get_image_pii_config() -> Dict[str, Any]:
    """Get image PII configuration from environment."""
    return {
        "enabled": os.environ.get("IMAGE_PII_ENABLED", "true").lower() == "true",
        "ocr_engine": os.environ.get("IMAGE_PII_OCR_ENGINE", "easyocr").lower(),
        "redaction_color": os.environ.get("IMAGE_REDACTION_COLOR", "black"),
        "use_blur": os.environ.get("IMAGE_PII_USE_BLUR", "false").lower() == "true",
        "blur_radius": int(os.environ.get("IMAGE_PII_BLUR_RADIUS", "15")),
        "padding": int(os.environ.get("IMAGE_PII_PADDING", "5")),
        # Redact entire OCR box when PII found (recommended for reliable coverage)
        # Set to "false" for legacy precise mode (less reliable with proportional fonts)
        "redact_full_box": os.environ.get("IMAGE_PII_REDACT_FULL_BOX", "true").lower() == "true",
    }


def parse_color(color_str: str) -> Tuple[int, int, int]:
    """Parse color string to RGB tuple."""
    color_str = color_str.lower().strip()

    # Named colors
    named_colors = {
        "black": (0, 0, 0),
        "white": (255, 255, 255),
        "red": (255, 0, 0),
        "green": (0, 255, 0),
        "blue": (0, 0, 255),
        "gray": (128, 128, 128),
        "grey": (128, 128, 128),
    }

    if color_str in named_colors:
        return named_colors[color_str]

    # Hex color (#RRGGBB or RRGGBB)
    if color_str.startswith("#"):
        color_str = color_str[1:]

    if len(color_str) == 6:
        try:
            r = int(color_str[0:2], 16)
            g = int(color_str[2:4], 16)
            b = int(color_str[4:6], 16)
            return (r, g, b)
        except ValueError:
            pass

    # Default to black
    return (0, 0, 0)


class ImagePIIRedactor:
    """Detect and redact PII in images using OCR + Presidio.

    Designed for Jetson Orin Nano with GPU memory management via ModelManager.
    Falls back to CPU mode on Mac or when CUDA unavailable.

    Usage:
        from mcp_vector_store.pii_protection import get_pii_protector

        pii_protector = get_pii_protector()
        redactor = ImagePIIRedactor(pii_protector=pii_protector)

        # Detect PII regions
        regions, ocr_result = redactor.detect_pii_regions("document.png")

        # Redact image
        result = redactor.redact_image("document.png", output_path="redacted.png")
    """

    def __init__(
        self,
        pii_protector: Optional["PIIProtector"] = None,
        ocr_engine: str = "easyocr",
        redaction_color: Tuple[int, int, int] = (0, 0, 0),
        use_blur: bool = False,
        blur_radius: int = 15,
        padding: int = 5,
        languages: List[str] = None,
        verbose: bool = False,
        redact_full_box: bool = True,
    ):
        """Initialize the image PII redactor.

        Args:
            pii_protector: PIIProtector instance for entity detection.
                          If None, will attempt to get the global instance.
            ocr_engine: OCR engine to use - "easyocr" or "tesseract"
            redaction_color: RGB tuple for redaction fill color
            use_blur: Use blur instead of solid fill
            blur_radius: Blur radius in pixels (if use_blur=True)
            padding: Extra pixels around detected regions
            languages: Languages for OCR (default: ["en"])
            verbose: Enable verbose logging
            redact_full_box: If True, redact entire OCR box when PII found (recommended).
                            If False, attempt precise sub-region redaction (less reliable).
        """
        self.verbose = verbose
        self.redaction_color = redaction_color
        self.use_blur = use_blur
        self.blur_radius = blur_radius
        self.padding = padding
        self.languages = languages or ["en"]
        self.redact_full_box = redact_full_box

        # Determine OCR engine
        self._ocr_engine = self._select_ocr_engine(ocr_engine)

        # EasyOCR reader (lazy loaded)
        self._easyocr_reader = None
        self._easyocr_loaded = False

        # GPU availability
        self._use_gpu = TORCH_AVAILABLE and torch.cuda.is_available()

        # PII protector (lazy loaded if not provided)
        self._pii_protector = pii_protector

        # Model manager reference (for GPU swapping)
        self._model_manager = None

        if self.verbose:
            print(f"ImagePIIRedactor: OCR engine={self._ocr_engine.value}, "
                  f"GPU={'yes' if self._use_gpu else 'no'}")

    def _select_ocr_engine(self, requested: str) -> OCREngine:
        """Select the best available OCR engine."""
        requested = requested.lower()

        if requested == "easyocr" and EASYOCR_AVAILABLE:
            return OCREngine.EASYOCR
        elif requested == "tesseract" and TESSERACT_AVAILABLE:
            return OCREngine.TESSERACT
        elif EASYOCR_AVAILABLE:
            if self.verbose:
                print(f"ImagePIIRedactor: Requested '{requested}' unavailable, "
                      f"falling back to EasyOCR")
            return OCREngine.EASYOCR
        elif TESSERACT_AVAILABLE:
            if self.verbose:
                print(f"ImagePIIRedactor: Requested '{requested}' unavailable, "
                      f"falling back to Tesseract")
            return OCREngine.TESSERACT
        else:
            raise RuntimeError(
                "No OCR engine available. Install easyocr or pytesseract."
            )

    def _get_pii_protector(self) -> Optional["PIIProtector"]:
        """Get the PII protector, loading lazily if needed."""
        if self._pii_protector is None:
            try:
                # Try relative import first (when imported as part of package)
                from .pii_protection import get_pii_protector
                self._pii_protector = get_pii_protector(verbose=self.verbose)
            except ImportError:
                try:
                    # Fall back to absolute import (when imported directly)
                    from pii_protection import get_pii_protector
                    self._pii_protector = get_pii_protector(verbose=self.verbose)
                except ImportError:
                    if self.verbose:
                        print("ImagePIIRedactor: PII protection not available")
                    return None
        return self._pii_protector

    def _get_model_manager(self) -> Optional["ModelManager"]:
        """Get the model manager for GPU swapping."""
        if self._model_manager is None:
            try:
                from .model_manager import get_model_manager
                self._model_manager = get_model_manager()
            except ImportError:
                pass
        return self._model_manager

    def _load_easyocr_reader(self):
        """Load the EasyOCR reader."""
        if self._easyocr_loaded:
            return

        if not EASYOCR_AVAILABLE:
            raise RuntimeError("EasyOCR not installed")

        if self.verbose:
            print(f"ImagePIIRedactor: Loading EasyOCR "
                  f"(GPU={'yes' if self._use_gpu else 'no'})...")
            start = time.time()

        self._easyocr_reader = easyocr.Reader(
            self.languages,
            gpu=self._use_gpu,
            verbose=self.verbose,
        )
        self._easyocr_loaded = True

        if self.verbose:
            elapsed = time.time() - start
            print(f"ImagePIIRedactor: EasyOCR loaded in {elapsed:.1f}s")

    def _unload_easyocr_reader(self):
        """Unload the EasyOCR reader to free memory."""
        if not self._easyocr_loaded:
            return

        if self.verbose:
            print("ImagePIIRedactor: Unloading EasyOCR...")

        del self._easyocr_reader
        self._easyocr_reader = None
        self._easyocr_loaded = False
        gc.collect()

        if self._use_gpu and TORCH_AVAILABLE:
            torch.cuda.empty_cache()

    def is_loaded(self) -> bool:
        """Check if OCR engine is loaded."""
        if self._ocr_engine == OCREngine.EASYOCR:
            return self._easyocr_loaded
        return True  # Tesseract doesn't need explicit loading

    def is_available(self) -> bool:
        """Check if image PII redaction is available."""
        if not PIL_AVAILABLE:
            return False

        if self._ocr_engine == OCREngine.EASYOCR:
            return EASYOCR_AVAILABLE
        elif self._ocr_engine == OCREngine.TESSERACT:
            return TESSERACT_AVAILABLE

        return False

    def _run_easyocr(self, image_path: str) -> OCRResult:
        """Run EasyOCR on an image.

        When GPU is available and OCR is registered with ModelManager,
        uses manager.require(ModelType.OCR) for coordinated GPU access.
        This ensures other GPU models are evicted first, checks circuit
        breaker, and holds refcount during inference to prevent eviction.
        """
        start = time.time()

        # Determine if we should use ModelManager for GPU coordination
        manager = None
        use_managed = False
        if self._use_gpu and not self._easyocr_loaded:
            manager = self._get_model_manager()
            if manager is not None:
                try:
                    from .model_manager import ModelType
                    use_managed = ModelType.OCR in manager._models
                except ImportError:
                    pass

        if use_managed:
            # Use require() context manager: loads model, holds refcount during
            # inference, auto-unloads transient model when done
            try:
                from .model_manager import ModelType
                with manager.require(ModelType.OCR):
                    results = self._easyocr_reader.readtext(image_path)
            except Exception as e:
                print(f"ImagePIIRedactor: GPU OCR load failed, falling back to CPU: {e}")
                self._use_gpu = False
                self._load_easyocr_reader()
                results = self._easyocr_reader.readtext(image_path)
        else:
            # No ModelManager or not registered — load directly
            if not self._easyocr_loaded:
                self._load_easyocr_reader()
            results = self._easyocr_reader.readtext(image_path)

        # Convert to OCRBox format
        boxes = []
        full_text_parts = []

        for detection in results:
            bbox, text, confidence = detection

            # EasyOCR returns 4 corner points [[x1,y1], [x2,y2], [x3,y3], [x4,y4]]
            # Convert to x, y, width, height
            x_coords = [p[0] for p in bbox]
            y_coords = [p[1] for p in bbox]
            x = int(min(x_coords))
            y = int(min(y_coords))
            width = int(max(x_coords) - x)
            height = int(max(y_coords) - y)

            boxes.append(OCRBox(
                text=text,
                x=x,
                y=y,
                width=width,
                height=height,
                confidence=confidence,
            ))
            full_text_parts.append(text)

        elapsed = (time.time() - start) * 1000

        return OCRResult(
            text=" ".join(full_text_parts),
            boxes=boxes,
            engine="easyocr",
            processing_time_ms=elapsed,
        )

    # Map 2-letter ISO codes to Tesseract 3-letter codes
    LANG_TO_TESSERACT = {
        "en": "eng", "fr": "fra", "de": "deu", "es": "spa",
        "it": "ita", "pt": "por", "nl": "nld", "ru": "rus",
        "zh": "chi_sim", "ja": "jpn", "ko": "kor", "ar": "ara",
    }

    def _tesseract_lang(self, lang: str) -> str:
        """Convert 2-letter language code to Tesseract 3-letter code."""
        return self.LANG_TO_TESSERACT.get(lang, lang)

    def _run_tesseract(self, image_path: str) -> OCRResult:
        """Run Tesseract OCR on an image."""
        if not TESSERACT_AVAILABLE:
            raise RuntimeError("Tesseract not installed")

        start = time.time()

        # Open image with PIL
        image = Image.open(image_path)

        # Get detailed OCR data with bounding boxes
        data = pytesseract.image_to_data(
            image,
            lang=self._tesseract_lang(self.languages[0]) if self.languages else "eng",
            output_type=pytesseract.Output.DICT,
        )

        # Convert to OCRBox format
        boxes = []
        full_text_parts = []

        n_boxes = len(data["text"])
        for i in range(n_boxes):
            text = data["text"][i].strip()
            conf = data["conf"][i]

            # Skip empty text and low confidence
            if not text or conf < 0:
                continue

            boxes.append(OCRBox(
                text=text,
                x=data["left"][i],
                y=data["top"][i],
                width=data["width"][i],
                height=data["height"][i],
                confidence=conf / 100.0,  # Tesseract returns 0-100
            ))
            full_text_parts.append(text)

        elapsed = (time.time() - start) * 1000

        return OCRResult(
            text=" ".join(full_text_parts),
            boxes=boxes,
            engine="tesseract",
            processing_time_ms=elapsed,
        )

    def run_ocr(self, image_path: str) -> OCRResult:
        """Run OCR on an image using the configured engine.

        Args:
            image_path: Path to image file

        Returns:
            OCRResult with extracted text and bounding boxes
        """
        if not os.path.exists(image_path):
            raise FileNotFoundError(f"Image not found: {image_path}")

        if self._ocr_engine == OCREngine.EASYOCR:
            return self._run_easyocr(image_path)
        else:
            return self._run_tesseract(image_path)

    def detect_pii_regions(
        self,
        image_path: str,
        session_id: Optional[str] = None,
    ) -> Tuple[List[ImagePIIRegion], OCRResult]:
        """Detect PII regions in an image.

        Args:
            image_path: Path to image file
            session_id: Optional PII session ID for tracking

        Returns:
            Tuple of (list of PII regions, OCR result)
        """
        # Run OCR
        ocr_result = self.run_ocr(image_path)

        # Get PII protector
        pii_protector = self._get_pii_protector()
        if pii_protector is None:
            # No PII detection available
            return [], ocr_result

        # Detect PII in each OCR box
        regions = []

        # Ensure Presidio is initialized (lazy initialization)
        if hasattr(pii_protector, '_ensure_initialized'):
            pii_protector._ensure_initialized()

        for box in ocr_result.boxes:
            # Run Presidio analyzer on the text
            if hasattr(pii_protector, '_analyzer') and pii_protector._analyzer is not None:
                try:
                    results = pii_protector._analyzer.analyze(
                        text=box.text,
                        language="en",
                    )

                    for result in results:
                        # Calculate bounding box for the PII region
                        # By default (redact_full_box=True), uses entire OCR box for reliability
                        pii_x, pii_y, pii_width, pii_height = box.calculate_pii_bbox(
                            pii_start=result.start,
                            pii_end=result.end,
                            redact_full_box=self.redact_full_box,
                        )

                        # Create a PII region for this detection
                        regions.append(ImagePIIRegion(
                            x=pii_x,
                            y=pii_y,
                            width=pii_width,
                            height=pii_height,
                            pii_type=result.entity_type,
                            original_text=box.text[result.start:result.end],
                            confidence=result.score,
                        ))
                except Exception as e:
                    if self.verbose:
                        print(f"ImagePIIRedactor: PII detection error: {e}")

        return regions, ocr_result

    def redact_region(
        self,
        image: "Image.Image",
        region: ImagePIIRegion,
    ) -> "Image.Image":
        """Apply redaction to a single region.

        Args:
            image: PIL Image to modify
            region: PII region to redact

        Returns:
            Modified image
        """
        if not PIL_AVAILABLE:
            raise RuntimeError("PIL not available")

        # Calculate padded bounding box
        x1 = max(0, region.x - self.padding)
        y1 = max(0, region.y - self.padding)
        x2 = min(image.width, region.x + region.width + self.padding)
        y2 = min(image.height, region.y + region.height + self.padding)

        if self.use_blur:
            # Extract region, blur it, paste back
            region_crop = image.crop((x1, y1, x2, y2))
            blurred = region_crop.filter(
                ImageFilter.GaussianBlur(radius=self.blur_radius)
            )
            image.paste(blurred, (x1, y1))
        else:
            # Draw solid rectangle
            draw = ImageDraw.Draw(image)
            draw.rectangle([x1, y1, x2, y2], fill=self.redaction_color)

        return image

    def redact_image(
        self,
        image_path: str,
        output_path: Optional[str] = None,
        session_id: Optional[str] = None,
        store_original: bool = True,
    ) -> RedactionResult:
        """Detect and redact PII from an image.

        Args:
            image_path: Path to input image
            output_path: Path for redacted image (auto-generated if None)
            session_id: Optional PII session ID for tracking
            store_original: Whether to keep the original image

        Returns:
            RedactionResult with paths and metadata
        """
        start = time.time()

        if not PIL_AVAILABLE:
            raise RuntimeError("PIL not available for image redaction")

        if not os.path.exists(image_path):
            raise FileNotFoundError(f"Image not found: {image_path}")

        # Detect PII regions
        regions, ocr_result = self.detect_pii_regions(image_path, session_id)

        # Load image
        image = Image.open(image_path).convert("RGB")

        # Apply redactions
        for region in regions:
            image = self.redact_region(image, region)

        # Determine output path
        if output_path is None:
            # Generate output path in redacted directory
            input_path = Path(image_path)
            redacted_dir = input_path.parent.parent / "redacted" / "images"
            redacted_dir.mkdir(parents=True, exist_ok=True)

            # Add hash to filename to avoid collisions
            file_hash = hashlib.md5(image_path.encode()).hexdigest()[:8]
            output_path = str(
                redacted_dir / f"{input_path.stem}_{file_hash}_redacted{input_path.suffix}"
            )

        # Save redacted image
        image.save(output_path)

        elapsed = (time.time() - start) * 1000

        return RedactionResult(
            redacted_image_path=output_path,
            original_image_path=image_path if store_original else None,
            regions_redacted=regions,
            session_id=session_id,
            processing_time_ms=elapsed + ocr_result.processing_time_ms,
            ocr_engine=ocr_result.engine,
        )


# Global instance (lazy initialization)
_global_image_pii_redactor: Optional[ImagePIIRedactor] = None


def get_image_pii_redactor(
    pii_protector: Optional["PIIProtector"] = None,
    verbose: bool = False,
) -> ImagePIIRedactor:
    """Get the global ImagePIIRedactor instance.

    Creates the instance on first call with configuration from environment.

    Args:
        pii_protector: Optional PIIProtector to use
        verbose: Enable verbose logging

    Returns:
        Global ImagePIIRedactor instance
    """
    global _global_image_pii_redactor

    if _global_image_pii_redactor is None:
        config = get_image_pii_config()

        _global_image_pii_redactor = ImagePIIRedactor(
            pii_protector=pii_protector,
            ocr_engine=config["ocr_engine"],
            redaction_color=parse_color(config["redaction_color"]),
            use_blur=config["use_blur"],
            blur_radius=config["blur_radius"],
            padding=config["padding"],
            verbose=verbose,
            redact_full_box=config["redact_full_box"],
        )

    return _global_image_pii_redactor
