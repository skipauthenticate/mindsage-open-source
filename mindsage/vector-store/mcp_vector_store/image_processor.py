"""Image processing for captioning and indexing.

Uses BLIP (via transformers) for image-to-text captioning.
Integrates with ModelManager for GPU memory swapping on Jetson.
Supports optional PII redaction via ImagePIIRedactor.

Default model: Salesforce/blip-image-captioning-base (~990MB disk, ~1-1.5GB VRAM)
"""

import gc
import os
import time
from typing import Optional, Dict, Any, TYPE_CHECKING

from .model_manager import get_model_manager, ModelType

if TYPE_CHECKING:
    from .image_pii_redactor import ImagePIIRedactor


# Supported image formats
IMAGE_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.gif', '.webp', '.bmp', '.tiff', '.tif'}

# Default captioning model
DEFAULT_CAPTION_MODEL = "Salesforce/blip-image-captioning-base"


class ImageProcessor:
    """Generate text captions for images using BLIP.

    Designed for batch processing on Jetson Orin Nano.
    Uses ModelManager to swap GPU models (unloads embedding before loading BLIP).

    Usage:
        processor = ImageProcessor()
        result = processor.process("photo.jpg")
        # result = {"text": "[Image: a cat sitting on a couch]\n\n...", "metadata": {...}}
    """

    def __init__(
        self,
        model_name: str = DEFAULT_CAPTION_MODEL,
        device: Optional[str] = None,
        verbose: bool = False,
        pii_redactor: Optional["ImagePIIRedactor"] = None,
        redact_on_process: bool = False,
    ):
        self.model_name = model_name
        self.verbose = verbose
        self._pipeline = None
        self._is_loaded = False

        # PII redaction settings
        self._pii_redactor = pii_redactor
        self._redact_on_process = redact_on_process

        # Auto-detect device
        if device is None:
            try:
                import torch
                self.device = "cuda" if torch.cuda.is_available() else "cpu"
            except ImportError:
                self.device = "cpu"
        else:
            self.device = device

        # Register with ModelManager
        self._register_with_manager()

    def _register_with_manager(self):
        """Register this processor with the global ModelManager."""
        manager = get_model_manager()
        manager.register_caption(self)

    def _load_model(self):
        """Load the BLIP captioning pipeline.

        ModelManager handles pre-flight memory checks and circuit breaking.
        On GPU failure, falls back to CPU automatically.
        """
        if self._is_loaded:
            return

        if self.verbose:
            print(f"ImageProcessor: Loading {self.model_name} on {self.device}...")
            start = time.time()

        from transformers import pipeline

        try:
            self._pipeline = pipeline(
                "image-to-text",
                model=self.model_name,
                device=0 if self.device == "cuda" else -1,
            )
            self._is_loaded = True
            if self.verbose:
                elapsed = time.time() - start
                print(f"ImageProcessor: Loaded on {self.device} in {elapsed:.1f}s")
        except Exception as e:
            if self.device == "cuda":
                print(f"ImageProcessor: GPU load failed ({e}), falling back to CPU...")
                self.device = "cpu"
                try:
                    self._pipeline = pipeline(
                        "image-to-text",
                        model=self.model_name,
                        device=-1,
                    )
                    self._is_loaded = True
                    if self.verbose:
                        elapsed = time.time() - start
                        print(f"ImageProcessor: Loaded on CPU (fallback) in {elapsed:.1f}s")
                except Exception as cpu_error:
                    raise RuntimeError(
                        f"Failed to load BLIP on both GPU and CPU. "
                        f"GPU error: {e}. CPU error: {cpu_error}"
                    ) from cpu_error
            else:
                raise RuntimeError(
                    f"Failed to load BLIP on {self.device}: {e}"
                ) from e

    def _unload_model(self):
        """Unload the BLIP pipeline to free memory."""
        if not self._is_loaded:
            return

        if self.verbose:
            print("ImageProcessor: Unloading BLIP model...")

        del self._pipeline
        self._pipeline = None
        self._is_loaded = False
        gc.collect()

        try:
            import torch
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except ImportError:
            pass

    def is_loaded(self) -> bool:
        return self._is_loaded

    @staticmethod
    def is_supported(file_path: str) -> bool:
        """Check if file is a supported image format."""
        ext = os.path.splitext(file_path)[1].lower()
        return ext in IMAGE_EXTENSIONS

    @staticmethod
    def get_image_metadata(file_path: str) -> Dict[str, Any]:
        """Extract image metadata (dimensions, format)."""
        metadata: Dict[str, Any] = {
            "media_type": "image",
            "format": os.path.splitext(file_path)[1].lower().lstrip('.'),
            "file_size_bytes": os.path.getsize(file_path),
        }

        try:
            from PIL import Image
            with Image.open(file_path) as img:
                metadata["width"] = img.width
                metadata["height"] = img.height
                metadata["image_mode"] = img.mode  # RGB, RGBA, L, etc.
                if hasattr(img, 'format') and img.format:
                    metadata["format"] = img.format.lower()
        except Exception as e:
            if metadata.get("format") == "":
                metadata["format"] = "unknown"

        return metadata

    def caption(self, file_path: str, max_new_tokens: int = 50) -> str:
        """Generate a text caption for an image.

        Uses ModelManager to ensure GPU is available (swaps out other models).

        Args:
            file_path: Path to image file
            max_new_tokens: Maximum tokens in generated caption

        Returns:
            Caption text

        Raises:
            FileNotFoundError: If image file doesn't exist
            RuntimeError: If captioning fails
        """
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"Image file not found: {file_path}")

        from PIL import Image

        # Load image with context manager to avoid resource leak
        try:
            with Image.open(file_path) as img:
                image = img.convert("RGB")
        except Image.DecompressionBombError as e:
            raise ValueError(f"Image too large (possible decompression bomb): {e}") from e
        except (IOError, OSError) as e:
            raise ValueError(f"Cannot read image file: {e}") from e

        manager = get_model_manager()

        with manager.require(ModelType.CAPTION):
            if self.verbose:
                print(f"ImageProcessor: Captioning {os.path.basename(file_path)}...")
                start = time.time()

            try:
                result = self._pipeline(
                    image,
                    max_new_tokens=max_new_tokens,
                )
            except Exception as e:
                raise RuntimeError(
                    f"BLIP captioning failed for {os.path.basename(file_path)}: {e}"
                ) from e

            # Pipeline returns list of dicts with 'generated_text'
            caption_text = result[0]["generated_text"].strip()

            if self.verbose:
                elapsed = time.time() - start
                print(f"ImageProcessor: Caption: '{caption_text}' ({elapsed:.1f}s)")

            return caption_text

    def process(
        self,
        file_path: str,
        redact_pii: Optional[bool] = None,
        session_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Process an image file: generate caption, extract metadata, and optionally redact PII.

        Uses parallel approach: caption original for best quality, redact separately for display.

        Args:
            file_path: Path to image file
            redact_pii: Override default redact_on_process setting
            session_id: Optional PII session ID for tracking

        Returns:
            Dict with 'text' (caption for indexing), 'metadata' (image info),
            and optionally 'pii_redaction' (redaction details)
        """
        metadata = self.get_image_metadata(file_path)

        # Caption the ORIGINAL image for best quality
        caption = self.caption(file_path)

        metadata["original_filename"] = os.path.basename(file_path)
        metadata["caption_model"] = self.model_name
        metadata["caption"] = caption

        # Build dimensions string
        dims_str = ""
        if "width" in metadata and "height" in metadata:
            dims_str = f", {metadata['width']}x{metadata['height']}"

        # Format for indexing - caption becomes the searchable text
        prefixed_text = f"[Image: {caption}{dims_str}]\n\nCaption: {caption}"

        result = {
            "text": prefixed_text,
            "metadata": metadata,
        }

        # PII redaction (parallel approach: redact separately, keep original caption)
        should_redact = redact_pii if redact_pii is not None else self._redact_on_process
        if should_redact and self._pii_redactor is not None:
            try:
                redaction_result = self._pii_redactor.redact_image(
                    file_path,
                    session_id=session_id,
                )
                result["pii_redaction"] = {
                    "redacted_image_path": redaction_result.redacted_image_path,
                    "original_image_path": redaction_result.original_image_path,
                    "regions_count": len(redaction_result.regions_redacted),
                    "pii_types_found": list(set(
                        r.pii_type for r in redaction_result.regions_redacted
                    )),
                    "session_id": redaction_result.session_id,
                    "processing_time_ms": redaction_result.processing_time_ms,
                    "ocr_engine": redaction_result.ocr_engine,
                }
                if self.verbose:
                    print(f"ImageProcessor: Redacted {len(redaction_result.regions_redacted)} "
                          f"PII regions in {redaction_result.processing_time_ms:.0f}ms")
            except Exception as e:
                if self.verbose:
                    print(f"ImageProcessor: PII redaction failed: {e}")
                result["pii_redaction"] = {
                    "error": str(e),
                    "redacted_image_path": None,
                }

        return result
