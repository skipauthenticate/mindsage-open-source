"""File processing utilities for extracting text from various file formats."""

import os
from typing import Optional, Dict, Any
from pathlib import Path

from .markdown_converter import MarkdownConverter
from .audio_processor import AUDIO_EXTENSIONS
from .image_processor import IMAGE_EXTENSIONS


class FileProcessor:
    """Extract text content from various file formats."""

    # Supported file extensions (text-based)
    SUPPORTED_EXTENSIONS = {
        '.txt', '.md', '.py', '.js', '.java', '.c', '.cpp', '.h',
        '.json', '.xml', '.html', '.css', '.yml', '.yaml', '.sh',
        '.rst', '.log', '.csv', '.tsv', '.pdf'
    }

    # Media file extensions (require ML processing)
    MEDIA_EXTENSIONS = AUDIO_EXTENSIONS | IMAGE_EXTENSIONS

    @classmethod
    def is_supported(cls, file_path: str) -> bool:
        """Check if file format is supported (text or media).

        Args:
            file_path: Path to file

        Returns:
            True if supported, False otherwise
        """
        ext = Path(file_path).suffix.lower()
        return ext in cls.SUPPORTED_EXTENSIONS or ext in cls.MEDIA_EXTENSIONS

    @classmethod
    def is_media_file(cls, file_path: str) -> bool:
        """Check if file is an audio or image file requiring ML processing."""
        ext = Path(file_path).suffix.lower()
        return ext in cls.MEDIA_EXTENSIONS

    @classmethod
    def is_audio_file(cls, file_path: str) -> bool:
        """Check if file is an audio file."""
        ext = Path(file_path).suffix.lower()
        return ext in AUDIO_EXTENSIONS

    @classmethod
    def is_image_file(cls, file_path: str) -> bool:
        """Check if file is an image file."""
        ext = Path(file_path).suffix.lower()
        return ext in IMAGE_EXTENSIONS

    @classmethod
    def extract_text(cls, file_path: str, encoding: str = 'utf-8') -> str:
        """Extract text from a file.

        Args:
            file_path: Path to file
            encoding: Text encoding (default: utf-8)

        Returns:
            Extracted text content

        Raises:
            FileNotFoundError: If file doesn't exist
            ValueError: If file format not supported
            UnicodeDecodeError: If encoding is incorrect
        """
        # Validate file exists
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"File not found: {file_path}")

        # Check if supported
        if not cls.is_supported(file_path):
            ext = Path(file_path).suffix.lower()
            raise ValueError(
                f"Unsupported file format: {ext}. "
                f"Supported formats: {', '.join(sorted(cls.SUPPORTED_EXTENSIONS | cls.MEDIA_EXTENSIONS))}"
            )

        # Media files need ML processing — use process_media_file instead
        if cls.is_media_file(file_path):
            raise ValueError(
                f"Media files ({Path(file_path).suffix.lower()}) require ML processing. "
                f"Use FileProcessor.process_media_file() instead of extract_text()."
            )

        # Extract text based on file type
        path = Path(file_path)
        ext = path.suffix.lower()

        # PDF files
        if ext == '.pdf':
            return cls._read_pdf_file(file_path)

        # Plain text files
        elif ext in {'.txt', '.md', '.log', '.py', '.js', '.java', '.c', '.cpp',
                   '.h', '.sh', '.rst', '.yml', '.yaml', '.html', '.css', '.xml'}:
            return cls._read_text_file(file_path, encoding)

        # CSV/TSV files
        elif ext in {'.csv', '.tsv'}:
            return cls._read_csv_file(file_path, encoding)

        # JSON files
        elif ext == '.json':
            return cls._read_json_file(file_path, encoding)

        else:
            # Fallback to text read
            return cls._read_text_file(file_path, encoding)

    @staticmethod
    def _read_text_file(file_path: str, encoding: str = 'utf-8') -> str:
        """Read plain text file.

        Args:
            file_path: Path to file
            encoding: Text encoding

        Returns:
            File contents as string
        """
        with open(file_path, 'r', encoding=encoding) as f:
            return f.read()

    @staticmethod
    def _read_csv_file(file_path: str, encoding: str = 'utf-8') -> str:
        """Read CSV/TSV file and convert to text.

        Args:
            file_path: Path to CSV/TSV file
            encoding: Text encoding

        Returns:
            CSV contents as formatted text
        """
        import csv

        path = Path(file_path)
        delimiter = '\t' if path.suffix.lower() == '.tsv' else ','

        rows = []
        with open(file_path, 'r', encoding=encoding) as f:
            reader = csv.reader(f, delimiter=delimiter)
            for row in reader:
                rows.append(' | '.join(row))

        return '\n'.join(rows)

    @staticmethod
    def _read_json_file(file_path: str, encoding: str = 'utf-8') -> str:
        """Read JSON file and convert to text.

        Args:
            file_path: Path to JSON file
            encoding: Text encoding

        Returns:
            JSON contents as formatted text
        """
        import json

        with open(file_path, 'r', encoding=encoding) as f:
            data = json.load(f)

        # Pretty print JSON
        return json.dumps(data, indent=2, ensure_ascii=False)

    @staticmethod
    def _read_pdf_file(file_path: str) -> str:
        """Read PDF file and extract text.

        Args:
            file_path: Path to PDF file

        Returns:
            Extracted text from all pages
        """
        from pypdf import PdfReader

        reader = PdfReader(file_path)
        text_parts = []

        for page_num, page in enumerate(reader.pages):
            page_text = page.extract_text()
            if page_text:
                text_parts.append(f"--- Page {page_num + 1} ---\n{page_text}")

        return '\n\n'.join(text_parts)

    @classmethod
    def get_file_metadata(cls, file_path: str) -> Dict[str, Any]:
        """Extract metadata from file.

        Args:
            file_path: Path to file

        Returns:
            Dictionary with file metadata
        """
        path = Path(file_path)
        stat = path.stat()

        return {
            'filename': path.name,
            'extension': path.suffix.lower(),
            'size_bytes': stat.st_size,
            'created_at': stat.st_ctime,
            'modified_at': stat.st_mtime,
            'absolute_path': str(path.absolute())
        }

    @classmethod
    def process_file(
        cls,
        file_path: str,
        encoding: str = 'utf-8',
        include_metadata: bool = True,
        generate_markdown: bool = True,
        audio_processor=None,
        image_processor=None,
    ) -> Dict[str, Any]:
        """Process file and extract both text and metadata.

        For media files (audio/image), delegates to the appropriate ML processor.
        For text files, extracts text directly.

        Args:
            file_path: Path to file
            encoding: Text encoding
            include_metadata: Whether to include file metadata
            generate_markdown: Whether to generate markdown representation
            audio_processor: AudioProcessor instance (required for audio files)
            image_processor: ImageProcessor instance (required for image files)

        Returns:
            Dictionary with 'text', 'markdown_content', and optionally 'metadata'
        """
        # Route media files to ML processors
        if cls.is_media_file(file_path):
            return cls.process_media_file(
                file_path,
                audio_processor=audio_processor,
                image_processor=image_processor,
            )

        text = cls.extract_text(file_path, encoding)

        result = {'text': text}

        if include_metadata:
            result['metadata'] = cls.get_file_metadata(file_path)

        # Generate markdown representation for viewing
        if generate_markdown:
            path = Path(file_path)
            result['markdown_content'] = MarkdownConverter.convert(
                text=text,
                filename=path.name,
                extension=path.suffix.lower()
            )

        return result

    @classmethod
    def process_media_file(
        cls,
        file_path: str,
        audio_processor=None,
        image_processor=None,
        redact_pii: bool = True,
    ) -> Dict[str, Any]:
        """Process an audio or image file using ML processors.

        Args:
            file_path: Path to media file
            audio_processor: AudioProcessor instance
            image_processor: ImageProcessor instance
            redact_pii: Whether to detect and redact PII (default: True)
                For audio: produces both original_transcript and redacted_transcript
                For images: handled separately by AsyncImageRedactor

        Returns:
            Dictionary with 'text' and 'metadata'
            For audio with PII redaction:
                - text: Redacted transcript (for embeddings/LLM)
                - metadata.original_transcript: Full text (for Explore tab)
                - metadata.redacted_transcript: PII replaced
                - metadata.has_pii: Boolean
                - metadata.pii_regions: List with timestamps

        Raises:
            ValueError: If no appropriate processor is available
        """
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"File not found: {file_path}")

        if cls.is_audio_file(file_path):
            if audio_processor is None:
                raise ValueError(
                    "Audio processing requires an AudioProcessor instance. "
                    "Audio support may not be enabled on this server."
                )
            # Use PII-aware processing for audio
            return audio_processor.process_with_pii_redaction(
                file_path,
                redact_pii=redact_pii,
            )

        elif cls.is_image_file(file_path):
            if image_processor is None:
                raise ValueError(
                    "Image processing requires an ImageProcessor instance. "
                    "Image support may not be enabled on this server."
                )
            # Image PII redaction is handled by AsyncImageRedactor
            return image_processor.process(file_path)

        else:
            ext = Path(file_path).suffix.lower()
            raise ValueError(f"Not a recognized media file: {ext}")


# Convenience functions
def extract_text_from_file(file_path: str, encoding: str = 'utf-8') -> str:
    """Extract text from a file.

    Args:
        file_path: Path to file
        encoding: Text encoding

    Returns:
        Extracted text

    Example:
        text = extract_text_from_file('document.txt')
    """
    return FileProcessor.extract_text(file_path, encoding)


def is_file_supported(file_path: str) -> bool:
    """Check if file format is supported.

    Args:
        file_path: Path to file

    Returns:
        True if supported

    Example:
        if is_file_supported('data.txt'):
            text = extract_text_from_file('data.txt')
    """
    return FileProcessor.is_supported(file_path)
