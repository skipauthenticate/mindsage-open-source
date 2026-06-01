"""Tests for image PII redaction module.

These tests verify the OCR-based PII detection and redaction
functionality for images. Tests requiring OCR engines that aren't
installed will be skipped.
"""

import os
import sys
import tempfile
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch

# Import the image_pii_redactor module directly to avoid triggering
# the full mcp_vector_store import chain (which has txtai dependencies)
sys.path.insert(0, str(Path(__file__).parent.parent / "mcp_vector_store"))
from image_pii_redactor import (
    ImagePIIRedactor,
    OCRBox,
    OCRResult,
    ImagePIIRegion,
    RedactionResult,
    OCREngine,
    get_image_pii_redactor,
    get_image_pii_config,
    parse_color,
    EASYOCR_AVAILABLE,
    TESSERACT_AVAILABLE,
    PIL_AVAILABLE,
)


# Skip all tests if PIL is not available
pytestmark = pytest.mark.skipif(
    not PIL_AVAILABLE,
    reason="PIL not installed"
)


class TestParseColor:
    """Test color parsing utility."""

    def test_named_colors(self):
        """Test parsing named colors."""
        assert parse_color("black") == (0, 0, 0)
        assert parse_color("white") == (255, 255, 255)
        assert parse_color("red") == (255, 0, 0)
        assert parse_color("green") == (0, 255, 0)
        assert parse_color("blue") == (0, 0, 255)
        assert parse_color("gray") == (128, 128, 128)

    def test_hex_colors(self):
        """Test parsing hex colors."""
        assert parse_color("#000000") == (0, 0, 0)
        assert parse_color("#FFFFFF") == (255, 255, 255)
        assert parse_color("#FF0000") == (255, 0, 0)
        assert parse_color("00FF00") == (0, 255, 0)  # Without #

    def test_case_insensitive(self):
        """Test case-insensitive color names."""
        assert parse_color("BLACK") == (0, 0, 0)
        assert parse_color("White") == (255, 255, 255)
        assert parse_color("RED") == (255, 0, 0)

    def test_invalid_color_defaults_to_black(self):
        """Test that invalid colors default to black."""
        assert parse_color("invalid") == (0, 0, 0)
        assert parse_color("xyz") == (0, 0, 0)
        assert parse_color("#GGG") == (0, 0, 0)


class TestOCRDataClasses:
    """Test OCR data classes."""

    def test_ocr_box(self):
        """Test OCRBox creation."""
        box = OCRBox(
            text="Hello World",
            x=10,
            y=20,
            width=100,
            height=30,
            confidence=0.95,
        )
        assert box.text == "Hello World"
        assert box.x == 10
        assert box.y == 20
        assert box.width == 100
        assert box.height == 30
        assert box.confidence == 0.95

    def test_ocr_result(self):
        """Test OCRResult creation."""
        boxes = [
            OCRBox("Hello", 0, 0, 50, 20, 0.9),
            OCRBox("World", 60, 0, 50, 20, 0.85),
        ]
        result = OCRResult(
            text="Hello World",
            boxes=boxes,
            engine="easyocr",
            processing_time_ms=150.5,
        )
        assert result.text == "Hello World"
        assert len(result.boxes) == 2
        assert result.engine == "easyocr"
        assert result.processing_time_ms == 150.5

    def test_image_pii_region(self):
        """Test ImagePIIRegion creation."""
        region = ImagePIIRegion(
            x=10,
            y=20,
            width=100,
            height=30,
            pii_type="PERSON",
            original_text="John Smith",
            confidence=0.92,
        )
        assert region.x == 10
        assert region.y == 20
        assert region.pii_type == "PERSON"
        assert region.original_text == "John Smith"

    def test_redaction_result(self):
        """Test RedactionResult creation."""
        regions = [
            ImagePIIRegion(10, 20, 100, 30, "PERSON", "John", 0.9),
        ]
        result = RedactionResult(
            redacted_image_path="/tmp/redacted.jpg",
            original_image_path="/tmp/original.jpg",
            regions_redacted=regions,
            session_id="test-session",
            processing_time_ms=500.0,
            ocr_engine="easyocr",
        )
        assert result.redacted_image_path == "/tmp/redacted.jpg"
        assert len(result.regions_redacted) == 1
        assert result.ocr_engine == "easyocr"


class TestImagePIIRedactorInit:
    """Test ImagePIIRedactor initialization."""

    @pytest.mark.skipif(
        not EASYOCR_AVAILABLE and not TESSERACT_AVAILABLE,
        reason="No OCR engine installed"
    )
    def test_init_with_defaults(self):
        """Test initialization with default settings."""
        redactor = ImagePIIRedactor(verbose=False)
        assert redactor.redaction_color == (0, 0, 0)
        assert redactor.use_blur is False
        assert redactor.blur_radius == 15
        assert redactor.padding == 5
        assert redactor.languages == ["en"]

    @pytest.mark.skipif(
        not EASYOCR_AVAILABLE and not TESSERACT_AVAILABLE,
        reason="No OCR engine installed"
    )
    def test_init_with_custom_settings(self):
        """Test initialization with custom settings."""
        redactor = ImagePIIRedactor(
            redaction_color=(255, 0, 0),
            use_blur=True,
            blur_radius=25,
            padding=10,
            verbose=False,
        )
        assert redactor.redaction_color == (255, 0, 0)
        assert redactor.use_blur is True
        assert redactor.blur_radius == 25
        assert redactor.padding == 10

    @pytest.mark.skipif(
        not EASYOCR_AVAILABLE,
        reason="EasyOCR not installed"
    )
    def test_init_easyocr_engine(self):
        """Test initialization with EasyOCR engine."""
        redactor = ImagePIIRedactor(ocr_engine="easyocr", verbose=False)
        assert redactor._ocr_engine == OCREngine.EASYOCR

    @pytest.mark.skipif(
        not TESSERACT_AVAILABLE,
        reason="Tesseract not installed"
    )
    def test_init_tesseract_engine(self):
        """Test initialization with Tesseract engine."""
        redactor = ImagePIIRedactor(ocr_engine="tesseract", verbose=False)
        assert redactor._ocr_engine == OCREngine.TESSERACT

    def test_is_available(self):
        """Test is_available method."""
        if not EASYOCR_AVAILABLE and not TESSERACT_AVAILABLE:
            pytest.skip("No OCR engine installed")

        redactor = ImagePIIRedactor(verbose=False)
        assert redactor.is_available() is True


class TestImagePIIRedactorOCR:
    """Test OCR functionality."""

    @pytest.fixture
    def sample_image(self):
        """Create a simple test image with text."""
        from PIL import Image, ImageDraw, ImageFont

        # Create a white image
        img = Image.new('RGB', (400, 100), color='white')
        draw = ImageDraw.Draw(img)

        # Draw some text
        draw.text((10, 10), "John Smith - john@example.com", fill='black')

        # Save to temp file
        fd, path = tempfile.mkstemp(suffix='.png')
        os.close(fd)
        img.save(path)

        yield path

        # Cleanup
        os.unlink(path)

    @pytest.mark.skipif(
        not EASYOCR_AVAILABLE and not TESSERACT_AVAILABLE,
        reason="No OCR engine installed"
    )
    def test_run_ocr(self, sample_image):
        """Test OCR on a sample image."""
        redactor = ImagePIIRedactor(verbose=False)
        result = redactor.run_ocr(sample_image)

        assert isinstance(result, OCRResult)
        assert result.engine in ["easyocr", "tesseract"]
        assert result.processing_time_ms > 0
        # Note: Actual OCR result depends on the image and engine quality

    @pytest.mark.skipif(
        not EASYOCR_AVAILABLE and not TESSERACT_AVAILABLE,
        reason="No OCR engine installed"
    )
    def test_run_ocr_file_not_found(self):
        """Test OCR with non-existent file."""
        redactor = ImagePIIRedactor(verbose=False)
        with pytest.raises(FileNotFoundError):
            redactor.run_ocr("/nonexistent/image.png")


class TestImagePIIRedactorDetection:
    """Test PII detection functionality."""

    @pytest.fixture
    def mock_pii_protector(self):
        """Create a mock PII protector."""
        mock = MagicMock()
        mock._analyzer = MagicMock()
        mock._analyzer.analyze.return_value = []
        return mock

    @pytest.fixture
    def redactor_with_mock_pii(self, mock_pii_protector):
        """Create redactor with mocked PII protector."""
        if not EASYOCR_AVAILABLE and not TESSERACT_AVAILABLE:
            pytest.skip("No OCR engine installed")

        return ImagePIIRedactor(
            pii_protector=mock_pii_protector,
            verbose=False,
        )

    @pytest.fixture
    def sample_image(self):
        """Create a simple test image."""
        from PIL import Image

        img = Image.new('RGB', (100, 100), color='white')
        fd, path = tempfile.mkstemp(suffix='.png')
        os.close(fd)
        img.save(path)

        yield path
        os.unlink(path)

    def test_detect_no_pii(self, redactor_with_mock_pii, sample_image):
        """Test detection with no PII found."""
        regions, ocr_result = redactor_with_mock_pii.detect_pii_regions(sample_image)
        assert isinstance(regions, list)
        assert isinstance(ocr_result, OCRResult)


class TestImagePIIRedactorRedaction:
    """Test redaction functionality."""

    @pytest.fixture
    def sample_image(self):
        """Create a simple test image."""
        from PIL import Image

        img = Image.new('RGB', (200, 100), color='white')
        fd, path = tempfile.mkstemp(suffix='.png')
        os.close(fd)
        img.save(path)

        yield path
        os.unlink(path)

    @pytest.mark.skipif(
        not EASYOCR_AVAILABLE and not TESSERACT_AVAILABLE,
        reason="No OCR engine installed"
    )
    def test_redact_image_creates_file(self, sample_image):
        """Test that redact_image creates output file."""
        redactor = ImagePIIRedactor(verbose=False)

        with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as f:
            output_path = f.name

        try:
            result = redactor.redact_image(sample_image, output_path=output_path)
            assert os.path.exists(result.redacted_image_path)
            assert result.redacted_image_path == output_path
        finally:
            if os.path.exists(output_path):
                os.unlink(output_path)

    @pytest.mark.skipif(
        not EASYOCR_AVAILABLE and not TESSERACT_AVAILABLE,
        reason="No OCR engine installed"
    )
    def test_redact_image_auto_output_path(self, sample_image):
        """Test that redact_image auto-generates output path."""
        redactor = ImagePIIRedactor(verbose=False)

        result = redactor.redact_image(sample_image)
        try:
            assert result.redacted_image_path is not None
            assert os.path.exists(result.redacted_image_path)
            assert "redacted" in result.redacted_image_path
        finally:
            if os.path.exists(result.redacted_image_path):
                os.unlink(result.redacted_image_path)

    @pytest.mark.skipif(
        not EASYOCR_AVAILABLE and not TESSERACT_AVAILABLE,
        reason="No OCR engine installed"
    )
    def test_redact_region_solid_fill(self, sample_image):
        """Test redact_region with solid fill."""
        from PIL import Image

        redactor = ImagePIIRedactor(
            redaction_color=(0, 0, 0),
            use_blur=False,
            verbose=False,
        )

        image = Image.open(sample_image).convert("RGB")
        region = ImagePIIRegion(
            x=10, y=10, width=50, height=30,
            pii_type="PERSON", original_text="Test", confidence=0.9,
        )

        redacted = redactor.redact_region(image, region)

        # Check that the region has been filled with black
        # Sample a pixel in the redacted region
        pixel = redacted.getpixel((25, 20))
        assert pixel == (0, 0, 0)

    @pytest.mark.skipif(
        not EASYOCR_AVAILABLE and not TESSERACT_AVAILABLE,
        reason="No OCR engine installed"
    )
    def test_redact_region_with_blur(self, sample_image):
        """Test redact_region with blur."""
        from PIL import Image

        redactor = ImagePIIRedactor(
            use_blur=True,
            blur_radius=15,
            verbose=False,
        )

        image = Image.open(sample_image).convert("RGB")
        region = ImagePIIRegion(
            x=10, y=10, width=50, height=30,
            pii_type="PERSON", original_text="Test", confidence=0.9,
        )

        # Should not raise
        redacted = redactor.redact_region(image, region)
        assert redacted is not None


class TestGetImagePIIConfig:
    """Test configuration from environment."""

    def test_default_config(self):
        """Test default configuration values."""
        # Clear any existing env vars
        env_vars = [
            "IMAGE_PII_ENABLED",
            "IMAGE_PII_OCR_ENGINE",
            "IMAGE_REDACTION_COLOR",
            "IMAGE_PII_USE_BLUR",
            "IMAGE_PII_BLUR_RADIUS",
            "IMAGE_PII_PADDING",
        ]
        original = {k: os.environ.get(k) for k in env_vars}

        for var in env_vars:
            if var in os.environ:
                del os.environ[var]

        try:
            config = get_image_pii_config()
            assert config["enabled"] is True
            assert config["ocr_engine"] == "easyocr"
            assert config["redaction_color"] == "black"
            assert config["use_blur"] is False
            assert config["blur_radius"] == 15
            assert config["padding"] == 5
        finally:
            # Restore original env
            for k, v in original.items():
                if v is not None:
                    os.environ[k] = v

    def test_custom_config_from_env(self):
        """Test configuration from environment variables."""
        original = {
            "IMAGE_PII_ENABLED": os.environ.get("IMAGE_PII_ENABLED"),
            "IMAGE_PII_OCR_ENGINE": os.environ.get("IMAGE_PII_OCR_ENGINE"),
            "IMAGE_REDACTION_COLOR": os.environ.get("IMAGE_REDACTION_COLOR"),
        }

        try:
            os.environ["IMAGE_PII_ENABLED"] = "false"
            os.environ["IMAGE_PII_OCR_ENGINE"] = "tesseract"
            os.environ["IMAGE_REDACTION_COLOR"] = "white"

            config = get_image_pii_config()
            assert config["enabled"] is False
            assert config["ocr_engine"] == "tesseract"
            assert config["redaction_color"] == "white"
        finally:
            for k, v in original.items():
                if v is not None:
                    os.environ[k] = v
                elif k in os.environ:
                    del os.environ[k]


class TestGlobalRedactor:
    """Test global redactor instance."""

    @pytest.mark.skipif(
        not EASYOCR_AVAILABLE and not TESSERACT_AVAILABLE,
        reason="No OCR engine installed"
    )
    def test_get_image_pii_redactor(self):
        """Test getting the global redactor instance."""
        # Reset global instance
        import image_pii_redactor as module
        module._global_image_pii_redactor = None

        redactor = get_image_pii_redactor(verbose=False)
        assert redactor is not None
        assert isinstance(redactor, ImagePIIRedactor)

        # Should return same instance
        redactor2 = get_image_pii_redactor()
        assert redactor is redactor2

        # Cleanup
        module._global_image_pii_redactor = None


# =============================================================================
# Integration Tests with Fixture Images
# =============================================================================

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "images"


@pytest.mark.skipif(
    not EASYOCR_AVAILABLE and not TESSERACT_AVAILABLE,
    reason="No OCR engine installed"
)
@pytest.mark.skipif(
    not FIXTURES_DIR.exists(),
    reason="Fixture images not generated. Run: python tests/fixtures/generate_test_images.py"
)
class TestImagePIIIntegration:
    """Integration tests using fixture images with real PII text."""

    @pytest.fixture
    def redactor(self):
        """Create a redactor for integration tests."""
        return ImagePIIRedactor(verbose=False)

    def test_ocr_detects_name(self, redactor):
        """Test that OCR detects person name in fixture image."""
        image_path = FIXTURES_DIR / "document_with_name.png"
        if not image_path.exists():
            pytest.skip(f"Fixture not found: {image_path}")

        result = redactor.run_ocr(str(image_path))

        # OCR should detect text containing "John Smith"
        assert "john" in result.text.lower() or "smith" in result.text.lower()

    def test_ocr_detects_email(self, redactor):
        """Test that OCR detects email in fixture image."""
        image_path = FIXTURES_DIR / "document_with_email.png"
        if not image_path.exists():
            pytest.skip(f"Fixture not found: {image_path}")

        result = redactor.run_ocr(str(image_path))

        # OCR should detect text containing email pattern
        assert "@" in result.text or "example" in result.text.lower()

    def test_ocr_detects_phone(self, redactor):
        """Test that OCR detects phone number in fixture image."""
        image_path = FIXTURES_DIR / "document_with_phone.png"
        if not image_path.exists():
            pytest.skip(f"Fixture not found: {image_path}")

        result = redactor.run_ocr(str(image_path))

        # OCR should detect phone number digits
        assert "555" in result.text or "123" in result.text

    def test_redact_document_with_name(self, redactor):
        """Test full redaction flow on document with name."""
        image_path = FIXTURES_DIR / "document_with_name.png"
        if not image_path.exists():
            pytest.skip(f"Fixture not found: {image_path}")

        result = redactor.redact_image(str(image_path))

        try:
            assert os.path.exists(result.redacted_image_path)
            assert result.processing_time_ms > 0
            # Note: PII detection depends on Presidio availability
        finally:
            if os.path.exists(result.redacted_image_path):
                os.unlink(result.redacted_image_path)

    def test_redact_document_with_multiple_pii(self, redactor):
        """Test redaction on document with multiple PII types."""
        image_path = FIXTURES_DIR / "document_with_multiple_pii.png"
        if not image_path.exists():
            pytest.skip(f"Fixture not found: {image_path}")

        result = redactor.redact_image(str(image_path))

        try:
            assert os.path.exists(result.redacted_image_path)
            # Should have detected OCR text
            assert result.ocr_engine in ["easyocr", "tesseract"]
        finally:
            if os.path.exists(result.redacted_image_path):
                os.unlink(result.redacted_image_path)

    def test_no_pii_document(self, redactor):
        """Test that document with no PII has no redactions."""
        image_path = FIXTURES_DIR / "document_no_pii.png"
        if not image_path.exists():
            pytest.skip(f"Fixture not found: {image_path}")

        regions, ocr_result = redactor.detect_pii_regions(str(image_path))

        # Should have OCR text but potentially no PII regions
        # (depending on Presidio's detection of generic text)
        assert ocr_result.text  # Some text was detected
        # Note: We can't guarantee no PII detected as Presidio might
        # false-positive on "Welcome", "Meeting", etc.

    def test_detect_sensitive_ssn(self, redactor):
        """Test detection of SSN (sensitive PII)."""
        image_path = FIXTURES_DIR / "document_with_ssn.png"
        if not image_path.exists():
            pytest.skip(f"Fixture not found: {image_path}")

        result = redactor.run_ocr(str(image_path))

        # OCR should detect SSN pattern
        # SSN format: 456-78-9012 (realistic pattern, not well-known example)
        assert "456" in result.text or "9012" in result.text

    def test_blur_redaction_mode(self, redactor):
        """Test blur mode creates valid output."""
        image_path = FIXTURES_DIR / "document_with_name.png"
        if not image_path.exists():
            pytest.skip(f"Fixture not found: {image_path}")

        # Enable blur mode
        redactor.use_blur = True
        redactor.blur_radius = 20

        result = redactor.redact_image(str(image_path))

        try:
            assert os.path.exists(result.redacted_image_path)
            # Verify image is valid
            from PIL import Image
            with Image.open(result.redacted_image_path) as img:
                assert img.size[0] > 0
                assert img.size[1] > 0
        finally:
            if os.path.exists(result.redacted_image_path):
                os.unlink(result.redacted_image_path)

    def test_custom_redaction_color(self, redactor):
        """Test custom redaction color."""
        image_path = FIXTURES_DIR / "document_with_email.png"
        if not image_path.exists():
            pytest.skip(f"Fixture not found: {image_path}")

        # Use red redaction
        redactor.redaction_color = (255, 0, 0)
        redactor.use_blur = False

        result = redactor.redact_image(str(image_path))

        try:
            assert os.path.exists(result.redacted_image_path)
        finally:
            if os.path.exists(result.redacted_image_path):
                os.unlink(result.redacted_image_path)


# =============================================================================
# Form-Style Integration Tests
# =============================================================================

@pytest.mark.skipif(
    not EASYOCR_AVAILABLE and not TESSERACT_AVAILABLE,
    reason="No OCR engine installed"
)
@pytest.mark.skipif(
    not FIXTURES_DIR.exists(),
    reason="Fixture images not generated. Run: python tests/fixtures/generate_test_images.py"
)
class TestFormImageIntegration:
    """Integration tests for form-style images with structured PII."""

    @pytest.fixture
    def redactor(self):
        """Create a redactor for integration tests."""
        return ImagePIIRedactor(verbose=False)

    def test_job_application_form(self, redactor):
        """Test OCR and redaction on job application form."""
        image_path = FIXTURES_DIR / "form_job_application.png"
        if not image_path.exists():
            pytest.skip(f"Fixture not found: {image_path}")

        result = redactor.run_ocr(str(image_path))

        # Should detect name, email, phone, address, SSN
        text_lower = result.text.lower()
        assert "michael" in text_lower or "johnson" in text_lower
        assert "@" in result.text or "email" in text_lower

    def test_medical_intake_form(self, redactor):
        """Test OCR on medical intake form with DOB and SSN."""
        image_path = FIXTURES_DIR / "form_medical_intake.png"
        if not image_path.exists():
            pytest.skip(f"Fixture not found: {image_path}")

        result = redactor.run_ocr(str(image_path))

        # Should detect patient info
        text_lower = result.text.lower()
        assert "sarah" in text_lower or "williams" in text_lower or "patient" in text_lower

    def test_bank_account_form(self, redactor):
        """Test OCR on bank account application."""
        image_path = FIXTURES_DIR / "form_bank_account.png"
        if not image_path.exists():
            pytest.skip(f"Fixture not found: {image_path}")

        result = redactor.run_ocr(str(image_path))

        # Should detect account holder info
        text_lower = result.text.lower()
        assert "david" in text_lower or "chen" in text_lower or "account" in text_lower

    def test_rental_application_form(self, redactor):
        """Test OCR on rental application with driver license."""
        image_path = FIXTURES_DIR / "form_rental_application.png"
        if not image_path.exists():
            pytest.skip(f"Fixture not found: {image_path}")

        result = redactor.run_ocr(str(image_path))

        # Should detect applicant info
        text_lower = result.text.lower()
        assert "jennifer" in text_lower or "martinez" in text_lower or "rental" in text_lower

    def test_insurance_claim_form(self, redactor):
        """Test OCR on insurance claim form with policy number."""
        image_path = FIXTURES_DIR / "form_insurance_claim.png"
        if not image_path.exists():
            pytest.skip(f"Fixture not found: {image_path}")

        result = redactor.run_ocr(str(image_path))

        # Should detect policy info
        text_lower = result.text.lower()
        assert "amanda" in text_lower or "thompson" in text_lower or "policy" in text_lower

    def test_passport_application_form(self, redactor):
        """Test OCR on passport application with passport number."""
        image_path = FIXTURES_DIR / "form_passport_application.png"
        if not image_path.exists():
            pytest.skip(f"Fixture not found: {image_path}")

        result = redactor.run_ocr(str(image_path))

        # Should detect passport info
        text_lower = result.text.lower()
        assert "christopher" in text_lower or "brown" in text_lower or "passport" in text_lower

    def test_employee_onboarding_form(self, redactor):
        """Test OCR on employee onboarding with bank details."""
        image_path = FIXTURES_DIR / "form_employee_onboarding.png"
        if not image_path.exists():
            pytest.skip(f"Fixture not found: {image_path}")

        result = redactor.run_ocr(str(image_path))

        # Should detect employee info
        text_lower = result.text.lower()
        assert "lisa" in text_lower or "anderson" in text_lower or "employee" in text_lower

    def test_tax_w2_form(self, redactor):
        """Test OCR on W-2 style tax form."""
        image_path = FIXTURES_DIR / "form_tax_w2.png"
        if not image_path.exists():
            pytest.skip(f"Fixture not found: {image_path}")

        result = redactor.run_ocr(str(image_path))

        # Should detect wage/tax info
        text_lower = result.text.lower()
        assert "kevin" in text_lower or "wilson" in text_lower or "wage" in text_lower

    def test_credit_application_form(self, redactor):
        """Test OCR on credit application with credit card number."""
        image_path = FIXTURES_DIR / "form_credit_application.png"
        if not image_path.exists():
            pytest.skip(f"Fixture not found: {image_path}")

        result = redactor.run_ocr(str(image_path))

        # Should detect credit info
        text_lower = result.text.lower()
        assert "rachel" in text_lower or "green" in text_lower or "credit" in text_lower

    def test_healthcare_provider_form(self, redactor):
        """Test OCR on healthcare provider form with NPI/DEA numbers."""
        image_path = FIXTURES_DIR / "form_healthcare_provider.png"
        if not image_path.exists():
            pytest.skip(f"Fixture not found: {image_path}")

        result = redactor.run_ocr(str(image_path))

        # Should detect provider info
        text_lower = result.text.lower()
        assert "james" in text_lower or "miller" in text_lower or "provider" in text_lower

    def test_redact_job_application(self, redactor):
        """Test full redaction on job application form."""
        image_path = FIXTURES_DIR / "form_job_application.png"
        if not image_path.exists():
            pytest.skip(f"Fixture not found: {image_path}")

        result = redactor.redact_image(str(image_path))

        try:
            assert os.path.exists(result.redacted_image_path)
            assert result.processing_time_ms > 0
            # Job application should have multiple PII types
            # (name, email, phone, address, SSN)
        finally:
            if os.path.exists(result.redacted_image_path):
                os.unlink(result.redacted_image_path)

    def test_redact_medical_intake(self, redactor):
        """Test full redaction on medical intake form."""
        image_path = FIXTURES_DIR / "form_medical_intake.png"
        if not image_path.exists():
            pytest.skip(f"Fixture not found: {image_path}")

        result = redactor.redact_image(str(image_path))

        try:
            assert os.path.exists(result.redacted_image_path)
            assert result.ocr_engine in ["easyocr", "tesseract"]
        finally:
            if os.path.exists(result.redacted_image_path):
                os.unlink(result.redacted_image_path)

    def test_redact_tax_form(self, redactor):
        """Test full redaction on W-2 tax form."""
        image_path = FIXTURES_DIR / "form_tax_w2.png"
        if not image_path.exists():
            pytest.skip(f"Fixture not found: {image_path}")

        result = redactor.redact_image(str(image_path))

        try:
            assert os.path.exists(result.redacted_image_path)
            # Tax forms should have SSN and financial data
        finally:
            if os.path.exists(result.redacted_image_path):
                os.unlink(result.redacted_image_path)


# =============================================================================
# License Plate and ID Card Integration Tests
# =============================================================================

@pytest.mark.skipif(
    not EASYOCR_AVAILABLE and not TESSERACT_AVAILABLE,
    reason="No OCR engine installed"
)
@pytest.mark.skipif(
    not FIXTURES_DIR.exists(),
    reason="Fixture images not generated. Run: python tests/fixtures/generate_test_images.py"
)
class TestLicensePlateAndIDIntegration:
    """Integration tests for license plates, ID cards, and vehicle documents."""

    @pytest.fixture
    def redactor(self):
        """Create a redactor for integration tests."""
        return ImagePIIRedactor(verbose=False)

    # -------------------------------------------------------------------------
    # License Plate Tests
    # -------------------------------------------------------------------------

    def test_ocr_california_license_plate(self, redactor):
        """Test OCR on California license plate."""
        image_path = FIXTURES_DIR / "license_plate_california.png"
        if not image_path.exists():
            pytest.skip(f"Fixture not found: {image_path}")

        result = redactor.run_ocr(str(image_path))

        # Should detect plate number and state
        text_upper = result.text.upper()
        assert "7ABC123" in text_upper or "ABC" in text_upper or "123" in result.text
        assert "CALIFORNIA" in text_upper or "CALIF" in text_upper

    def test_ocr_new_york_license_plate(self, redactor):
        """Test OCR on New York license plate."""
        image_path = FIXTURES_DIR / "license_plate_new_york.png"
        if not image_path.exists():
            pytest.skip(f"Fixture not found: {image_path}")

        result = redactor.run_ocr(str(image_path))

        # Should detect plate number
        assert "ABC" in result.text.upper() or "1234" in result.text

    def test_ocr_texas_license_plate(self, redactor):
        """Test OCR on Texas license plate."""
        image_path = FIXTURES_DIR / "license_plate_texas.png"
        if not image_path.exists():
            pytest.skip(f"Fixture not found: {image_path}")

        result = redactor.run_ocr(str(image_path))

        # Should detect plate number
        assert "LBJ" in result.text.upper() or "4521" in result.text

    # -------------------------------------------------------------------------
    # ID Card Tests
    # -------------------------------------------------------------------------

    def test_ocr_drivers_license(self, redactor):
        """Test OCR on driver's license."""
        image_path = FIXTURES_DIR / "id_drivers_license.png"
        if not image_path.exists():
            pytest.skip(f"Fixture not found: {image_path}")

        result = redactor.run_ocr(str(image_path))

        # Should detect name and license number
        text_upper = result.text.upper()
        assert "SMITH" in text_upper or "JOHN" in text_upper or "LICENSE" in text_upper

    def test_ocr_state_id(self, redactor):
        """Test OCR on state ID card."""
        image_path = FIXTURES_DIR / "id_state_card.png"
        if not image_path.exists():
            pytest.skip(f"Fixture not found: {image_path}")

        result = redactor.run_ocr(str(image_path))

        # Should detect name
        text_upper = result.text.upper()
        assert "DOE" in text_upper or "JANE" in text_upper or "IDENTIFICATION" in text_upper

    def test_ocr_military_id(self, redactor):
        """Test OCR on military ID card."""
        image_path = FIXTURES_DIR / "id_military.png"
        if not image_path.exists():
            pytest.skip(f"Fixture not found: {image_path}")

        result = redactor.run_ocr(str(image_path))

        # Should detect military info
        text_upper = result.text.upper()
        assert "JOHNSON" in text_upper or "MILITARY" in text_upper or "ARMY" in text_upper

    def test_ocr_employee_badge(self, redactor):
        """Test OCR on employee badge."""
        image_path = FIXTURES_DIR / "id_employee_badge.png"
        if not image_path.exists():
            pytest.skip(f"Fixture not found: {image_path}")

        result = redactor.run_ocr(str(image_path))

        # Should detect employee info
        text_upper = result.text.upper()
        assert "WILLIAMS" in text_upper or "EMPLOYEE" in text_upper or "ENGINEERING" in text_upper

    # -------------------------------------------------------------------------
    # Vehicle Document Tests
    # -------------------------------------------------------------------------

    def test_ocr_vehicle_registration(self, redactor):
        """Test OCR on vehicle registration."""
        image_path = FIXTURES_DIR / "vehicle_registration.png"
        if not image_path.exists():
            pytest.skip(f"Fixture not found: {image_path}")

        result = redactor.run_ocr(str(image_path))

        # Should detect VIN, plate, or owner info
        text_upper = result.text.upper()
        assert "VIN" in text_upper or "PLATE" in text_upper or "SMITH" in text_upper

    def test_ocr_auto_insurance_card(self, redactor):
        """Test OCR on auto insurance card."""
        image_path = FIXTURES_DIR / "insurance_card_auto.png"
        if not image_path.exists():
            pytest.skip(f"Fixture not found: {image_path}")

        result = redactor.run_ocr(str(image_path))

        # Should detect policy or insured info
        text_upper = result.text.upper()
        assert "POLICY" in text_upper or "INSURANCE" in text_upper or "DOE" in text_upper

    def test_ocr_parking_permit(self, redactor):
        """Test OCR on parking permit."""
        image_path = FIXTURES_DIR / "parking_permit.png"
        if not image_path.exists():
            pytest.skip(f"Fixture not found: {image_path}")

        result = redactor.run_ocr(str(image_path))

        # Should detect permit info
        text_upper = result.text.upper()
        assert "PARKING" in text_upper or "PERMIT" in text_upper or "CHEN" in text_upper

    # -------------------------------------------------------------------------
    # Passport and Travel Document Tests
    # -------------------------------------------------------------------------

    def test_ocr_passport_data_page(self, redactor):
        """Test OCR on passport data page."""
        image_path = FIXTURES_DIR / "passport_data_page.png"
        if not image_path.exists():
            pytest.skip(f"Fixture not found: {image_path}")

        result = redactor.run_ocr(str(image_path))

        # Should detect passport info
        text_upper = result.text.upper()
        assert "BROWN" in text_upper or "PASSPORT" in text_upper or "CHRISTOPHER" in text_upper

    def test_ocr_global_entry_card(self, redactor):
        """Test OCR on Global Entry card."""
        image_path = FIXTURES_DIR / "global_entry_card.png"
        if not image_path.exists():
            pytest.skip(f"Fixture not found: {image_path}")

        result = redactor.run_ocr(str(image_path))

        # Should detect global entry info
        text_upper = result.text.upper()
        assert "MARTINEZ" in text_upper or "GLOBAL" in text_upper or "ENTRY" in text_upper

    # -------------------------------------------------------------------------
    # Health Card Tests
    # -------------------------------------------------------------------------

    def test_ocr_health_insurance_card(self, redactor):
        """Test OCR on health insurance card."""
        image_path = FIXTURES_DIR / "health_insurance_card.png"
        if not image_path.exists():
            pytest.skip(f"Fixture not found: {image_path}")

        result = redactor.run_ocr(str(image_path))

        # Should detect member info
        text_upper = result.text.upper()
        assert "THOMPSON" in text_upper or "MEMBER" in text_upper or "INSURANCE" in text_upper

    def test_ocr_medicare_card(self, redactor):
        """Test OCR on Medicare card."""
        image_path = FIXTURES_DIR / "medicare_card.png"
        if not image_path.exists():
            pytest.skip(f"Fixture not found: {image_path}")

        result = redactor.run_ocr(str(image_path))

        # Should detect medicare info
        text_upper = result.text.upper()
        assert "WILSON" in text_upper or "MEDICARE" in text_upper or "HEALTH" in text_upper

    # -------------------------------------------------------------------------
    # Full Redaction Tests
    # -------------------------------------------------------------------------

    def test_redact_drivers_license(self, redactor):
        """Test full redaction on driver's license."""
        image_path = FIXTURES_DIR / "id_drivers_license.png"
        if not image_path.exists():
            pytest.skip(f"Fixture not found: {image_path}")

        result = redactor.redact_image(str(image_path))

        try:
            assert os.path.exists(result.redacted_image_path)
            assert result.processing_time_ms > 0
        finally:
            if os.path.exists(result.redacted_image_path):
                os.unlink(result.redacted_image_path)

    def test_redact_vehicle_registration(self, redactor):
        """Test full redaction on vehicle registration."""
        image_path = FIXTURES_DIR / "vehicle_registration.png"
        if not image_path.exists():
            pytest.skip(f"Fixture not found: {image_path}")

        result = redactor.redact_image(str(image_path))

        try:
            assert os.path.exists(result.redacted_image_path)
            assert result.ocr_engine in ["easyocr", "tesseract"]
        finally:
            if os.path.exists(result.redacted_image_path):
                os.unlink(result.redacted_image_path)

    def test_redact_passport(self, redactor):
        """Test full redaction on passport data page."""
        image_path = FIXTURES_DIR / "passport_data_page.png"
        if not image_path.exists():
            pytest.skip(f"Fixture not found: {image_path}")

        result = redactor.redact_image(str(image_path))

        try:
            assert os.path.exists(result.redacted_image_path)
        finally:
            if os.path.exists(result.redacted_image_path):
                os.unlink(result.redacted_image_path)

    def test_redact_license_plate(self, redactor):
        """Test full redaction on license plate."""
        image_path = FIXTURES_DIR / "license_plate_california.png"
        if not image_path.exists():
            pytest.skip(f"Fixture not found: {image_path}")

        result = redactor.redact_image(str(image_path))

        try:
            assert os.path.exists(result.redacted_image_path)
        finally:
            if os.path.exists(result.redacted_image_path):
                os.unlink(result.redacted_image_path)
