#!/usr/bin/env python3
"""Generate test images with PII text for integration testing.

Run this script to create test images in tests/fixtures/images/.
These images contain clear text that OCR engines should detect reliably.

Usage:
    python tests/fixtures/generate_test_images.py
"""

import os
from pathlib import Path

try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError:
    print("PIL not installed. Run: pip install Pillow")
    exit(1)


# Output directory
FIXTURES_DIR = Path(__file__).parent / "images"


def get_font(size: int = 24):
    """Get a font for drawing text. Falls back to default if custom font not available."""
    # Try to use a common system font for better OCR detection
    font_paths = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",  # Linux
        "/usr/share/fonts/TTF/DejaVuSans.ttf",  # Arch Linux
        "/System/Library/Fonts/Helvetica.ttc",  # macOS
        "/System/Library/Fonts/SFNSText.ttf",  # macOS
        "C:\\Windows\\Fonts\\arial.ttf",  # Windows
    ]

    for path in font_paths:
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size)
            except Exception:
                pass

    # Fall back to default font
    try:
        return ImageFont.truetype("DejaVuSans.ttf", size)
    except Exception:
        return ImageFont.load_default()


def create_image_with_text(
    filename: str,
    lines: list,
    width: int = 600,
    height: int = 200,
    font_size: int = 28,
    bg_color: str = "white",
    text_color: str = "black",
):
    """Create an image with text lines."""
    img = Image.new("RGB", (width, height), color=bg_color)
    draw = ImageDraw.Draw(img)
    font = get_font(font_size)

    # Calculate starting Y position to center text vertically
    line_height = font_size + 10
    total_height = len(lines) * line_height
    y = (height - total_height) // 2

    for line in lines:
        # Center each line horizontally
        bbox = draw.textbbox((0, 0), line, font=font)
        text_width = bbox[2] - bbox[0]
        x = (width - text_width) // 2
        draw.text((x, y), line, fill=text_color, font=font)
        y += line_height

    output_path = FIXTURES_DIR / filename
    img.save(output_path, "PNG")
    print(f"Created: {output_path}")
    return output_path


def create_form_image(
    filename: str,
    title: str,
    fields: list,
    width: int = 650,
    height: int = 400,
    title_size: int = 26,
    label_size: int = 18,
    value_size: int = 20,
    bg_color: str = "white",
    title_color: str = "darkblue",
    label_color: str = "gray",
    value_color: str = "black",
    border_color: str = "lightgray",
):
    """Create a form-style image with labeled fields.

    Args:
        filename: Output filename
        title: Form title
        fields: List of (label, value) tuples
        width, height: Image dimensions
        title_size, label_size, value_size: Font sizes
        bg_color, title_color, label_color, value_color: Colors
        border_color: Color for field borders
    """
    img = Image.new("RGB", (width, height), color=bg_color)
    draw = ImageDraw.Draw(img)

    title_font = get_font(title_size)
    label_font = get_font(label_size)
    value_font = get_font(value_size)

    # Draw title centered at top
    title_bbox = draw.textbbox((0, 0), title, font=title_font)
    title_width = title_bbox[2] - title_bbox[0]
    title_x = (width - title_width) // 2
    draw.text((title_x, 20), title, fill=title_color, font=title_font)

    # Draw underline below title
    draw.line([(50, 55), (width - 50, 55)], fill=title_color, width=2)

    # Draw form fields
    field_start_y = 80
    field_height = 50
    label_x = 40
    value_x = 200
    field_width = width - 80

    for i, (label, value) in enumerate(fields):
        y = field_start_y + i * field_height

        # Draw field box
        box_y = y + 5
        draw.rectangle(
            [(label_x - 5, box_y), (label_x + field_width, box_y + field_height - 10)],
            outline=border_color,
            width=1
        )

        # Draw label
        draw.text((label_x, y + 8), f"{label}:", fill=label_color, font=label_font)

        # Draw value
        draw.text((value_x, y + 10), value, fill=value_color, font=value_font)

    output_path = FIXTURES_DIR / filename
    img.save(output_path, "PNG")
    print(f"Created: {output_path}")
    return output_path


def create_license_plate_image(
    filename: str,
    plate_text: str,
    state: str = "CALIFORNIA",
    width: int = 400,
    height: int = 200,
    plate_color: str = "white",
    text_color: str = "darkblue",
    border_color: str = "darkblue",
):
    """Create a simulated license plate image.

    Args:
        filename: Output filename
        plate_text: The license plate number
        state: State name to display
        width, height: Image dimensions
        plate_color, text_color, border_color: Colors
    """
    img = Image.new("RGB", (width, height), color=plate_color)
    draw = ImageDraw.Draw(img)

    # Draw border
    draw.rectangle([(5, 5), (width - 5, height - 5)], outline=border_color, width=3)

    # Draw state name at top
    state_font = get_font(18)
    state_bbox = draw.textbbox((0, 0), state, font=state_font)
    state_width = state_bbox[2] - state_bbox[0]
    draw.text(((width - state_width) // 2, 20), state, fill="red", font=state_font)

    # Draw plate number large in center
    plate_font = get_font(48)
    plate_bbox = draw.textbbox((0, 0), plate_text, font=plate_font)
    plate_width = plate_bbox[2] - plate_bbox[0]
    plate_height = plate_bbox[3] - plate_bbox[1]
    draw.text(
        ((width - plate_width) // 2, (height - plate_height) // 2 + 10),
        plate_text,
        fill=text_color,
        font=plate_font
    )

    output_path = FIXTURES_DIR / filename
    img.save(output_path, "PNG")
    print(f"Created: {output_path}")
    return output_path


def create_id_card_image(
    filename: str,
    card_type: str,
    fields: list,
    width: int = 550,
    height: int = 350,
    header_color: str = "darkblue",
    bg_color: str = "white",
    text_color: str = "black",
):
    """Create a simulated ID card image (driver's license, state ID, etc).

    Args:
        filename: Output filename
        card_type: Type of ID (e.g., "DRIVER LICENSE", "STATE ID")
        fields: List of (label, value) tuples
        width, height: Image dimensions
        header_color, bg_color, text_color: Colors
    """
    img = Image.new("RGB", (width, height), color=bg_color)
    draw = ImageDraw.Draw(img)

    # Draw header bar
    draw.rectangle([(0, 0), (width, 50)], fill=header_color)

    # Draw card type in header
    header_font = get_font(22)
    header_bbox = draw.textbbox((0, 0), card_type, font=header_font)
    header_width = header_bbox[2] - header_bbox[0]
    draw.text(((width - header_width) // 2, 12), card_type, fill="white", font=header_font)

    # Draw photo placeholder on left
    photo_x, photo_y = 20, 70
    photo_w, photo_h = 120, 150
    draw.rectangle(
        [(photo_x, photo_y), (photo_x + photo_w, photo_y + photo_h)],
        outline="gray",
        width=2
    )
    # Add "PHOTO" text in placeholder
    photo_font = get_font(14)
    draw.text((photo_x + 35, photo_y + 65), "PHOTO", fill="gray", font=photo_font)

    # Draw fields on the right side
    label_font = get_font(12)
    value_font = get_font(16)
    field_x = 160
    field_y = 70
    line_height = 38

    for label, value in fields:
        # Draw label
        draw.text((field_x, field_y), label, fill="gray", font=label_font)
        # Draw value below label
        draw.text((field_x, field_y + 14), value, fill=text_color, font=value_font)
        field_y += line_height

    # Draw border
    draw.rectangle([(2, 2), (width - 2, height - 2)], outline="gray", width=1)

    output_path = FIXTURES_DIR / filename
    img.save(output_path, "PNG")
    print(f"Created: {output_path}")
    return output_path


def create_vehicle_document_image(
    filename: str,
    title: str,
    fields: list,
    width: int = 600,
    height: int = 400,
    title_color: str = "darkgreen",
    bg_color: str = "#f5f5dc",  # Beige
):
    """Create a simulated vehicle registration or insurance card.

    Args:
        filename: Output filename
        title: Document title
        fields: List of (label, value) tuples
        width, height: Image dimensions
        title_color, bg_color: Colors
    """
    img = Image.new("RGB", (width, height), color=bg_color)
    draw = ImageDraw.Draw(img)

    # Draw title
    title_font = get_font(24)
    title_bbox = draw.textbbox((0, 0), title, font=title_font)
    title_width = title_bbox[2] - title_bbox[0]
    draw.text(((width - title_width) // 2, 20), title, fill=title_color, font=title_font)

    # Draw decorative line
    draw.line([(30, 55), (width - 30, 55)], fill=title_color, width=2)

    # Draw fields in two columns
    label_font = get_font(14)
    value_font = get_font(16)
    col1_x = 40
    col2_x = width // 2 + 20
    start_y = 75
    line_height = 50

    for i, (label, value) in enumerate(fields):
        col_x = col1_x if i % 2 == 0 else col2_x
        row = i // 2
        y = start_y + row * line_height

        draw.text((col_x, y), label + ":", fill="gray", font=label_font)
        draw.text((col_x, y + 16), value, fill="black", font=value_font)

    # Draw border
    draw.rectangle([(5, 5), (width - 5, height - 5)], outline=title_color, width=2)

    output_path = FIXTURES_DIR / filename
    img.save(output_path, "PNG")
    print(f"Created: {output_path}")
    return output_path


def main():
    """Generate all test images."""
    FIXTURES_DIR.mkdir(parents=True, exist_ok=True)

    print("Generating test images for image PII redaction...")
    print(f"Output directory: {FIXTURES_DIR}\n")

    # 1. Image with person name
    create_image_with_text(
        "document_with_name.png",
        [
            "Employee Record",
            "Name: John Smith",
            "Department: Engineering",
        ],
        font_size=24,
    )

    # 2. Image with email address
    create_image_with_text(
        "document_with_email.png",
        [
            "Contact Information",
            "Email: john.smith@example.com",
            "Office: Building A, Room 101",
        ],
        font_size=24,
    )

    # 3. Image with phone number
    create_image_with_text(
        "document_with_phone.png",
        [
            "Emergency Contact",
            "Phone: 555-123-4567",
            "Available 24/7",
        ],
        font_size=24,
    )

    # 4. Image with SSN (sensitive)
    # Note: Use a realistic SSN pattern - "123-45-6789" is filtered by Presidio
    # as it's a well-known example SSN used in documentation
    create_image_with_text(
        "document_with_ssn.png",
        [
            "Tax Document",
            "SSN: 456-78-9012",
            "Tax Year: 2024",
        ],
        font_size=24,
    )

    # 5. Image with multiple PII types
    create_image_with_text(
        "document_with_multiple_pii.png",
        [
            "Application Form",
            "Applicant: Jane Doe",
            "Email: jane.doe@company.org",
            "Phone: 555-987-6543",
        ],
        height=250,
        font_size=22,
    )

    # 6. Image with no PII (negative test)
    create_image_with_text(
        "document_no_pii.png",
        [
            "Company Newsletter",
            "Welcome to the team!",
            "Meeting at 3pm today.",
        ],
        font_size=24,
    )

    # 7. Image with credit card (for testing critical PII)
    create_image_with_text(
        "document_with_credit_card.png",
        [
            "Payment Receipt",
            "Card: 4111-1111-1111-1111",
            "Amount: $99.99",
        ],
        font_size=24,
    )

    # 8. Image with IP address
    create_image_with_text(
        "document_with_ip.png",
        [
            "Server Log",
            "Client IP: 192.168.1.100",
            "Request: GET /api/data",
        ],
        font_size=24,
    )

    # =========================================================================
    # Form-style images with structured PII
    # =========================================================================

    # 9. Job Application Form
    create_form_image(
        "form_job_application.png",
        "JOB APPLICATION",
        [
            ("Full Name", "Michael Johnson"),
            ("Email", "michael.johnson@email.com"),
            ("Phone", "(555) 234-5678"),
            ("Address", "123 Main Street, Anytown, CA 90210"),
            ("SSN", "456-78-9012"),
        ],
        height=380,
    )

    # 10. Medical Intake Form
    create_form_image(
        "form_medical_intake.png",
        "PATIENT INTAKE FORM",
        [
            ("Patient Name", "Sarah Williams"),
            ("Date of Birth", "03/15/1985"),
            ("SSN", "789-01-2345"),
            ("Insurance ID", "XYZ123456789"),
            ("Phone", "555-345-6789"),
            ("Emergency Contact", "Robert Williams 555-456-7890"),
        ],
        height=420,
    )

    # 11. Bank Account Application
    create_form_image(
        "form_bank_account.png",
        "NEW ACCOUNT APPLICATION",
        [
            ("Account Holder", "David Chen"),
            ("SSN", "234-56-7890"),
            ("Date of Birth", "07/22/1990"),
            ("Phone", "555-567-8901"),
            ("Email", "david.chen@bankmail.com"),
            ("Address", "456 Oak Avenue, Suite 200"),
        ],
        height=420,
    )

    # 12. Rental Application
    create_form_image(
        "form_rental_application.png",
        "RENTAL APPLICATION",
        [
            ("Applicant", "Jennifer Martinez"),
            ("SSN", "345-67-8901"),
            ("Driver License", "D1234567"),
            ("Employer", "Tech Corp Inc."),
            ("Annual Income", "$85,000"),
            ("Phone", "(555) 678-9012"),
        ],
        height=420,
    )

    # 13. Insurance Claim Form
    create_form_image(
        "form_insurance_claim.png",
        "INSURANCE CLAIM FORM",
        [
            ("Policy Holder", "Amanda Thompson"),
            ("Policy Number", "POL-2024-78901234"),
            ("Date of Birth", "11/30/1988"),
            ("Phone", "555-789-0123"),
            ("Claim Amount", "$2,500.00"),
        ],
        height=380,
    )

    # 14. Passport Application Style
    create_form_image(
        "form_passport_application.png",
        "PASSPORT APPLICATION",
        [
            ("Full Legal Name", "Christopher Brown"),
            ("Date of Birth", "06/18/1982"),
            ("Place of Birth", "New York, NY, USA"),
            ("SSN", "567-89-0123"),
            ("Passport No.", "US123456789"),
            ("Phone", "555-890-1234"),
        ],
        height=420,
    )

    # 15. Employee Onboarding Form
    create_form_image(
        "form_employee_onboarding.png",
        "EMPLOYEE ONBOARDING",
        [
            ("Employee Name", "Lisa Anderson"),
            ("Employee ID", "EMP-2024-00123"),
            ("SSN", "678-90-1234"),
            ("Email", "l.anderson@company.com"),
            ("Bank Account", "****4567"),
            ("Routing Number", "021000021"),
        ],
        height=420,
    )

    # 16. Tax Form Style (W-2 like)
    create_form_image(
        "form_tax_w2.png",
        "WAGE AND TAX STATEMENT",
        [
            ("Employee Name", "Kevin Wilson"),
            ("SSN", "890-12-3456"),
            ("Employer EIN", "12-3456789"),
            ("Wages", "$72,500.00"),
            ("Federal Tax", "$14,500.00"),
            ("Address", "789 Pine Road, Boston, MA 02101"),
        ],
        height=420,
    )

    # 17. Credit Application
    create_form_image(
        "form_credit_application.png",
        "CREDIT APPLICATION",
        [
            ("Applicant", "Rachel Green"),
            ("SSN", "901-23-4567"),
            ("Date of Birth", "09/25/1991"),
            ("Annual Income", "$95,000"),
            ("Credit Card", "4111-1111-1111-1111"),  # Visa test card (passes Luhn)
            ("Phone", "(555) 012-3456"),
        ],
        height=420,
    )

    # 18. Healthcare Provider Form
    create_form_image(
        "form_healthcare_provider.png",
        "HEALTHCARE PROVIDER REGISTRATION",
        [
            ("Provider Name", "Dr. James Miller MD"),
            ("NPI Number", "1234567890"),
            ("DEA Number", "AM1234567"),
            ("License No.", "MD-2024-123456"),
            ("Phone", "555-234-5678"),
            ("Email", "dr.miller@healthcare.org"),
        ],
        height=420,
    )

    # =========================================================================
    # License Plate Images
    # =========================================================================

    # 19. California License Plate
    create_license_plate_image(
        "license_plate_california.png",
        "7ABC123",
        state="CALIFORNIA",
    )

    # 20. New York License Plate
    create_license_plate_image(
        "license_plate_new_york.png",
        "ABC-1234",
        state="NEW YORK",
        plate_color="#FFD700",  # Gold
        text_color="darkblue",
    )

    # 21. Texas License Plate
    create_license_plate_image(
        "license_plate_texas.png",
        "LBJ-4521",
        state="TEXAS",
    )

    # =========================================================================
    # ID Card Images (Driver's License, State ID, etc.)
    # =========================================================================

    # 22. Driver's License
    create_id_card_image(
        "id_drivers_license.png",
        "DRIVER LICENSE",
        [
            ("DL", "D1234567"),
            ("NAME", "SMITH, JOHN MICHAEL"),
            ("DOB", "03/15/1985"),
            ("ADDRESS", "123 MAIN ST APT 4B"),
            ("CITY", "LOS ANGELES, CA 90001"),
            ("EXPIRES", "03/15/2028"),
        ],
    )

    # 23. State ID Card
    create_id_card_image(
        "id_state_card.png",
        "STATE IDENTIFICATION CARD",
        [
            ("ID NO", "ID9876543"),
            ("NAME", "DOE, JANE MARIE"),
            ("DOB", "07/22/1990"),
            ("ADDRESS", "456 OAK AVENUE"),
            ("CITY", "SAN FRANCISCO, CA 94102"),
            ("EXPIRES", "07/22/2029"),
        ],
        header_color="darkgreen",
    )

    # 24. Military ID Style
    create_id_card_image(
        "id_military.png",
        "MILITARY ID CARD",
        [
            ("DOD ID", "1234567890"),
            ("NAME", "JOHNSON, ROBERT A"),
            ("RANK", "SGT"),
            ("BRANCH", "US ARMY"),
            ("DOB", "11/30/1988"),
            ("EXPIRES", "11/30/2026"),
        ],
        header_color="#4B5320",  # Army green
    )

    # 25. Employee Badge Style
    create_id_card_image(
        "id_employee_badge.png",
        "EMPLOYEE IDENTIFICATION",
        [
            ("EMP ID", "EMP-2024-00456"),
            ("NAME", "WILLIAMS, SARAH L"),
            ("DEPT", "ENGINEERING"),
            ("ACCESS", "LEVEL 3 - RESTRICTED"),
            ("EMAIL", "s.williams@corp.com"),
            ("PHONE", "555-123-4567"),
        ],
        header_color="#2F4F4F",  # Dark slate
    )

    # =========================================================================
    # Vehicle Documents
    # =========================================================================

    # 26. Vehicle Registration
    create_vehicle_document_image(
        "vehicle_registration.png",
        "VEHICLE REGISTRATION CARD",
        [
            ("PLATE", "7ABC123"),
            ("VIN", "1HGBH41JXMN109186"),
            ("OWNER", "JOHN M SMITH"),
            ("MAKE", "HONDA"),
            ("ADDRESS", "123 MAIN ST"),
            ("MODEL", "ACCORD"),
            ("CITY STATE", "LOS ANGELES CA"),
            ("YEAR", "2024"),
            ("REG EXPIRES", "12/31/2025"),
            ("COLOR", "SILVER"),
        ],
    )

    # 27. Auto Insurance Card
    create_vehicle_document_image(
        "insurance_card_auto.png",
        "AUTOMOBILE INSURANCE ID CARD",
        [
            ("POLICY NO", "AUT-2024-789456"),
            ("INSURED", "JANE DOE"),
            ("VEHICLE", "2023 TOYOTA CAMRY"),
            ("VIN", "4T1BF1FK5CU123456"),
            ("EFFECTIVE", "01/01/2024"),
            ("AGENT", "STATE FARM INS"),
            ("EXPIRES", "01/01/2025"),
            ("PHONE", "1-800-555-0199"),
        ],
        title_color="darkblue",
    )

    # 28. Parking Permit with Vehicle Info
    create_vehicle_document_image(
        "parking_permit.png",
        "PARKING PERMIT",
        [
            ("PERMIT NO", "PKG-2024-1234"),
            ("NAME", "MICHAEL CHEN"),
            ("PLATE", "ABC-5678"),
            ("VEHICLE", "BLUE FORD F150"),
            ("DEPT", "ENGINEERING"),
            ("VALID UNTIL", "12/31/2024"),
            ("LOT", "BUILDING A - LOT 3"),
            ("SPACE", "A-127"),
        ],
        title_color="purple",
        bg_color="#E6E6FA",  # Lavender
    )

    # =========================================================================
    # Passport and Travel Documents
    # =========================================================================

    # 29. Passport Data Page Style
    create_id_card_image(
        "passport_data_page.png",
        "UNITED STATES PASSPORT",
        [
            ("PASSPORT NO", "US123456789"),
            ("SURNAME", "BROWN"),
            ("GIVEN NAMES", "CHRISTOPHER JAMES"),
            ("DOB", "06/18/1982"),
            ("PLACE OF BIRTH", "NEW YORK, USA"),
            ("EXPIRES", "06/18/2034"),
        ],
        header_color="#1C2951",  # Navy blue
    )

    # 30. Global Entry Card Style
    create_id_card_image(
        "global_entry_card.png",
        "GLOBAL ENTRY",
        [
            ("PASS ID", "GE123456789"),
            ("NAME", "MARTINEZ, JENNIFER A"),
            ("DOB", "09/25/1991"),
            ("NATIONALITY", "USA"),
            ("EXPIRES", "09/25/2029"),
            ("ISSUED", "09/25/2024"),
        ],
        header_color="#003366",
    )

    # =========================================================================
    # Medical and Health Cards
    # =========================================================================

    # 31. Health Insurance Card
    create_id_card_image(
        "health_insurance_card.png",
        "HEALTH INSURANCE CARD",
        [
            ("MEMBER ID", "XYZ123456789"),
            ("NAME", "THOMPSON, AMANDA R"),
            ("GROUP NO", "GRP-98765"),
            ("DOB", "11/30/1988"),
            ("RX BIN", "003585"),
            ("PLAN", "PPO GOLD"),
        ],
        header_color="#0066CC",
    )

    # 32. Medicare Card Style
    create_id_card_image(
        "medicare_card.png",
        "MEDICARE HEALTH INSURANCE",
        [
            ("MEDICARE NO", "1EG4-TE5-MK72"),
            ("NAME", "WILSON, KEVIN D"),
            ("SEX", "MALE"),
            ("DOB", "05/10/1958"),
            ("HOSPITAL", "PART A 06-01-2023"),
            ("MEDICAL", "PART B 06-01-2023"),
        ],
        header_color="#CC0000",
    )

    print(f"\nGenerated {len(list(FIXTURES_DIR.glob('*.png')))} test images.")
    print("\nTo use in tests:")
    print('  pytest tests/test_image_pii_redactor.py -v')


if __name__ == "__main__":
    main()
