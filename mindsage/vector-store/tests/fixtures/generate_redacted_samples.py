#!/usr/bin/env python3
"""Generate sample redacted images for visual verification.

This script processes a subset of test images through the redactor
and saves the output for manual inspection.

Usage:
    python tests/fixtures/generate_redacted_samples.py
"""

import os
import sys
from pathlib import Path

# Add parent to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "mcp_vector_store"))

from image_pii_redactor import ImagePIIRedactor

# Directories
FIXTURES_DIR = Path(__file__).parent / "images"
OUTPUT_DIR = Path(__file__).parent / "redacted" / "images"


def main():
    """Generate redacted samples for visual inspection."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    print("Generating redacted image samples for visual verification...")
    print(f"Input directory: {FIXTURES_DIR}")
    print(f"Output directory: {OUTPUT_DIR}\n")

    # Initialize redactor
    redactor = ImagePIIRedactor(verbose=True)
    print(f"Using OCR engine: {redactor._ocr_engine.value}\n")

    # Sample images to process (representative of each category)
    sample_images = [
        # Basic documents
        "document_with_name.png",
        "document_with_email.png",
        "document_with_ssn.png",
        "document_with_multiple_pii.png",
        # Forms
        "form_job_application.png",
        "form_medical_intake.png",
        "form_tax_w2.png",
        # IDs and plates
        "id_drivers_license.png",
        "license_plate_california.png",
        "vehicle_registration.png",
        "passport_data_page.png",
        "health_insurance_card.png",
    ]

    processed = 0
    for image_name in sample_images:
        image_path = FIXTURES_DIR / image_name
        if not image_path.exists():
            print(f"SKIP: {image_name} (not found)")
            continue

        output_name = image_name.replace(".png", "_redacted.png")
        output_path = OUTPUT_DIR / output_name

        print(f"\nProcessing: {image_name}")
        print("-" * 50)

        try:
            # Run OCR first to show what was detected
            ocr_result = redactor.run_ocr(str(image_path))
            print(f"OCR Text ({len(ocr_result.boxes)} regions):")
            print(f"  {ocr_result.text[:200]}..." if len(ocr_result.text) > 200 else f"  {ocr_result.text}")

            # Detect PII regions
            pii_regions, _ = redactor.detect_pii_regions(str(image_path))
            print(f"\nPII Detected: {len(pii_regions)} regions")
            for region in pii_regions:
                print(f"  - {region.pii_type}: '{region.original_text}' (conf: {region.confidence:.2f})")

            # Redact and save
            result = redactor.redact_image(
                str(image_path),
                output_path=str(output_path),
                store_original=False,
            )

            print(f"\nRedacted: {output_path.name}")
            print(f"  Regions redacted: {len(result.regions_redacted)}")
            print(f"  Processing time: {result.processing_time_ms:.0f}ms")
            processed += 1

        except Exception as e:
            print(f"ERROR: {e}")

    print(f"\n{'=' * 50}")
    print(f"Generated {processed} redacted images in: {OUTPUT_DIR}")
    print("\nTo view the results:")
    print(f"  open {OUTPUT_DIR}")


if __name__ == "__main__":
    main()
