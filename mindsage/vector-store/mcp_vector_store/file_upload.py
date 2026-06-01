"""File upload handling for HTTP MCP server."""

import os
import tempfile
import base64
from typing import Optional, Dict, Any
from pathlib import Path


class FileUploadHandler:
    """Handle file uploads from remote clients."""

    def __init__(self, upload_dir: Optional[str] = None):
        """Initialize file upload handler.

        Args:
            upload_dir: Directory for temporary file storage
                       (defaults to system temp directory)
        """
        self.upload_dir = upload_dir or tempfile.gettempdir()
        self.temp_files = []  # Track temp files for cleanup

    def save_uploaded_file(
        self,
        file_content: bytes,
        filename: str,
        keep_temp: bool = False
    ) -> str:
        """Save uploaded file content to temporary file.

        Args:
            file_content: Binary file content
            filename: Original filename
            keep_temp: If False, track for cleanup

        Returns:
            Path to saved temporary file

        Example:
            temp_path = handler.save_uploaded_file(
                content,
                "document.txt"
            )
        """
        # Create unique temp file
        suffix = Path(filename).suffix or '.tmp'
        prefix = Path(filename).stem or 'upload'

        fd, temp_path = tempfile.mkstemp(
            suffix=suffix,
            prefix=f"{prefix}_",
            dir=self.upload_dir
        )

        # Write content
        with os.fdopen(fd, 'wb') as f:
            f.write(file_content)

        # Track for cleanup
        if not keep_temp:
            self.temp_files.append(temp_path)

        return temp_path

    def save_base64_file(
        self,
        base64_content: str,
        filename: str,
        keep_temp: bool = False
    ) -> str:
        """Save base64-encoded file content.

        Args:
            base64_content: Base64-encoded file content
            filename: Original filename
            keep_temp: If False, track for cleanup

        Returns:
            Path to saved temporary file

        Example:
            temp_path = handler.save_base64_file(
                base64_content,
                "document.pdf"
            )
        """
        # Decode base64
        file_content = base64.b64decode(base64_content)

        return self.save_uploaded_file(file_content, filename, keep_temp)

    def cleanup_temp_files(self):
        """Remove all tracked temporary files."""
        for temp_path in self.temp_files:
            try:
                if os.path.exists(temp_path):
                    os.unlink(temp_path)
            except Exception as e:
                # Log but don't fail
                print(f"Warning: Could not remove temp file {temp_path}: {e}")

        self.temp_files.clear()

    def cleanup_file(self, file_path: str):
        """Remove a specific temporary file.

        Args:
            file_path: Path to file to remove
        """
        try:
            if os.path.exists(file_path):
                os.unlink(file_path)
            if file_path in self.temp_files:
                self.temp_files.remove(file_path)
        except Exception as e:
            print(f"Warning: Could not remove file {file_path}: {e}")

    def __del__(self):
        """Cleanup temp files on destruction."""
        self.cleanup_temp_files()
