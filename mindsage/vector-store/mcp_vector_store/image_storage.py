"""Persistent image storage with PII redaction support.

Manages storage of original and redacted images for the MindSage vector store.
Ensures images are persisted to disk with proper naming and organization.

Storage layout:
    data/
    ├── uploads/images/          # Original images (user access only)
    │   └── img_{uuid}.{ext}
    └── redacted/images/         # Redacted images (LLM-safe)
        └── img_{uuid}_redacted.{ext}
"""

import os
import shutil
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from .image_pii_redactor import ImagePIIRedactor


@dataclass
class ImageStorageResult:
    """Result of storing an image with optional redaction."""
    original_image_path: str  # Path to stored original
    redacted_image_path: Optional[str]  # Path to redacted version (None if no PII)
    has_pii: bool  # Whether PII was detected
    pii_types_found: list  # List of PII types detected
    pii_regions_count: int  # Number of PII regions redacted
    image_id: str  # Unique identifier for this image


class ImageStorageManager:
    """Manages persistent storage of original and redacted images.

    Usage:
        storage = ImageStorageManager(
            uploads_dir="/app/data/uploads/images",
            redacted_dir="/app/data/redacted/images",
            pii_redactor=redactor,
        )

        result = storage.store_image(temp_file_path, "photo.jpg")
        # result.original_image_path = "/app/data/uploads/images/img_abc123.jpg"
        # result.redacted_image_path = "/app/data/redacted/images/img_abc123_redacted.jpg"
        # result.has_pii = True
    """

    def __init__(
        self,
        uploads_dir: str = "/app/data/uploads/images",
        redacted_dir: str = "/app/data/redacted/images",
        pii_redactor: Optional["ImagePIIRedactor"] = None,
        verbose: bool = False,
    ):
        """Initialize the image storage manager.

        Args:
            uploads_dir: Directory for original uploaded images
            redacted_dir: Directory for PII-redacted images
            pii_redactor: Optional ImagePIIRedactor instance for PII detection
            verbose: Enable verbose logging
        """
        self.uploads_dir = Path(uploads_dir)
        self.redacted_dir = Path(redacted_dir)
        self._pii_redactor = pii_redactor
        self.verbose = verbose

        # Create directories if they don't exist
        self.uploads_dir.mkdir(parents=True, exist_ok=True)
        self.redacted_dir.mkdir(parents=True, exist_ok=True)

    def _generate_image_id(self) -> str:
        """Generate a unique image ID."""
        return uuid.uuid4().hex[:12]

    def _get_extension(self, filename: str) -> str:
        """Extract file extension from filename."""
        ext = Path(filename).suffix.lower()
        return ext if ext else ".jpg"

    def store_image(
        self,
        source_path: str,
        original_filename: str,
        enable_redaction: bool = True,
        session_id: Optional[str] = None,
    ) -> ImageStorageResult:
        """Store an image with optional PII redaction.

        Args:
            source_path: Path to source image file (e.g., temp upload)
            original_filename: Original filename from upload
            enable_redaction: Whether to run PII redaction
            session_id: Optional PII session ID for tracking

        Returns:
            ImageStorageResult with paths and PII info
        """
        # Generate unique ID and paths
        image_id = self._generate_image_id()
        ext = self._get_extension(original_filename)

        original_path = self.uploads_dir / f"img_{image_id}{ext}"
        redacted_path = self.redacted_dir / f"img_{image_id}_redacted{ext}"

        if self.verbose:
            print(f"ImageStorage: Storing image {image_id} from {source_path}")

        # Copy original to persistent storage
        shutil.copy2(source_path, original_path)

        if self.verbose:
            print(f"ImageStorage: Saved original to {original_path}")

        # Run PII redaction if enabled and redactor available
        has_pii = False
        pii_types_found = []
        pii_regions_count = 0
        final_redacted_path: Optional[str] = None

        if enable_redaction and self._pii_redactor is not None:
            try:
                # Detect PII regions
                regions, ocr_result = self._pii_redactor.detect_pii_regions(str(original_path))

                if regions:
                    # PII detected - generate redacted image
                    has_pii = True
                    pii_types_found = list(set(r.pii_type for r in regions))
                    pii_regions_count = len(regions)

                    # Run redaction and save to redacted path
                    redaction_result = self._pii_redactor.redact_image(
                        str(original_path),
                        output_path=str(redacted_path),
                        session_id=session_id,
                    )
                    final_redacted_path = str(redacted_path)

                    if self.verbose:
                        print(f"ImageStorage: Detected {pii_regions_count} PII regions: {pii_types_found}")
                        print(f"ImageStorage: Saved redacted to {redacted_path}")
                else:
                    # No PII detected - redacted path points to original (no duplicate storage)
                    final_redacted_path = str(original_path)

                    if self.verbose:
                        print("ImageStorage: No PII detected, redacted path = original path")

            except Exception as e:
                if self.verbose:
                    print(f"ImageStorage: PII redaction failed: {e}")
                # On failure, redacted path points to original (fail-safe)
                final_redacted_path = str(original_path)
        else:
            # Redaction disabled - redacted path points to original
            final_redacted_path = str(original_path)

        return ImageStorageResult(
            original_image_path=str(original_path),
            redacted_image_path=final_redacted_path,
            has_pii=has_pii,
            pii_types_found=pii_types_found,
            pii_regions_count=pii_regions_count,
            image_id=image_id,
        )

    def store_image_deferred_redaction(
        self,
        source_path: str,
        original_filename: str,
    ) -> ImageStorageResult:
        """Store an image without running PII redaction (defer to async worker).

        Use this for fast uploads - redaction will be done in the background
        by AsyncImageRedactor, which will update document metadata when done.

        Args:
            source_path: Path to source image file (e.g., temp upload)
            original_filename: Original filename from upload

        Returns:
            ImageStorageResult with paths (redaction fields set to pending state)
        """
        # Generate unique ID and paths
        image_id = self._generate_image_id()
        ext = self._get_extension(original_filename)

        original_path = self.uploads_dir / f"img_{image_id}{ext}"
        redacted_path = self.redacted_dir / f"img_{image_id}_redacted{ext}"

        if self.verbose:
            print(f"ImageStorage: Storing image {image_id} (deferred redaction)")

        # Copy original to persistent storage
        shutil.copy2(source_path, original_path)

        if self.verbose:
            print(f"ImageStorage: Saved original to {original_path}")

        # Return result with redaction pending
        # Redacted path points to original for now (safe fallback)
        # AsyncImageRedactor will update metadata when redaction completes
        return ImageStorageResult(
            original_image_path=str(original_path),
            redacted_image_path=str(redacted_path),  # Target path for redacted version
            has_pii=False,  # Will be updated by async worker
            pii_types_found=[],  # Will be updated by async worker
            pii_regions_count=0,  # Will be updated by async worker
            image_id=image_id,
        )

    def delete_image(self, image_id: str) -> bool:
        """Delete an image and its redacted version.

        Args:
            image_id: The unique image ID

        Returns:
            True if at least one file was deleted
        """
        deleted = False

        # Find and delete original
        for ext in ['.jpg', '.jpeg', '.png', '.gif', '.webp', '.bmp']:
            original_path = self.uploads_dir / f"img_{image_id}{ext}"
            if original_path.exists():
                original_path.unlink()
                deleted = True
                if self.verbose:
                    print(f"ImageStorage: Deleted original {original_path}")

            redacted_path = self.redacted_dir / f"img_{image_id}_redacted{ext}"
            if redacted_path.exists():
                redacted_path.unlink()
                deleted = True
                if self.verbose:
                    print(f"ImageStorage: Deleted redacted {redacted_path}")

        return deleted

    def get_image_path(
        self,
        image_id: str,
        context: str = "user",
    ) -> Optional[str]:
        """Get the appropriate image path based on context.

        Args:
            image_id: The unique image ID
            context: Either "llm" (returns redacted) or "user" (returns original)

        Returns:
            Path to the appropriate image, or None if not found
        """
        # Find the image (try common extensions)
        for ext in ['.jpg', '.jpeg', '.png', '.gif', '.webp', '.bmp']:
            if context == "llm":
                # For LLM: prefer redacted, fall back to original
                redacted_path = self.redacted_dir / f"img_{image_id}_redacted{ext}"
                if redacted_path.exists():
                    return str(redacted_path)
                # Fall back to original (might point there if no PII)
                original_path = self.uploads_dir / f"img_{image_id}{ext}"
                if original_path.exists():
                    return str(original_path)
            else:
                # For user: always return original
                original_path = self.uploads_dir / f"img_{image_id}{ext}"
                if original_path.exists():
                    return str(original_path)

        return None


# Global instance
_global_image_storage: Optional[ImageStorageManager] = None


def get_image_storage(
    uploads_dir: str = "/app/data/uploads/images",
    redacted_dir: str = "/app/data/redacted/images",
    pii_redactor: Optional["ImagePIIRedactor"] = None,
    verbose: bool = False,
) -> ImageStorageManager:
    """Get or create the global ImageStorageManager instance.

    Args:
        uploads_dir: Directory for original uploads
        redacted_dir: Directory for redacted images
        pii_redactor: Optional PII redactor instance
        verbose: Enable verbose logging

    Returns:
        The global ImageStorageManager instance
    """
    global _global_image_storage
    if _global_image_storage is None:
        _global_image_storage = ImageStorageManager(
            uploads_dir=uploads_dir,
            redacted_dir=redacted_dir,
            pii_redactor=pii_redactor,
            verbose=verbose,
        )
    return _global_image_storage


def reset_image_storage() -> None:
    """Reset the global image storage instance (for testing)."""
    global _global_image_storage
    _global_image_storage = None
