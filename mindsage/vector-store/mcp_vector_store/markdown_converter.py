"""Convert various file content to well-formatted markdown for viewing."""

import re
import json
from typing import Optional, List, Tuple
from pathlib import Path


class MarkdownConverter:
    """Convert extracted file content to well-formatted markdown."""

    # Language mapping for code files
    LANGUAGE_MAP = {
        '.py': 'python',
        '.js': 'javascript',
        '.ts': 'typescript',
        '.tsx': 'typescript',
        '.jsx': 'javascript',
        '.java': 'java',
        '.c': 'c',
        '.cpp': 'cpp',
        '.h': 'c',
        '.sh': 'bash',
        '.go': 'go',
        '.rs': 'rust',
        '.rb': 'ruby',
        '.php': 'php',
        '.swift': 'swift',
        '.kt': 'kotlin',
        '.scala': 'scala',
        '.r': 'r',
        '.sql': 'sql',
        '.html': 'html',
        '.css': 'css',
        '.xml': 'xml',
        '.yml': 'yaml',
        '.yaml': 'yaml',
        '.json': 'json',
    }

    # Code file extensions
    CODE_EXTENSIONS = {
        '.py', '.js', '.ts', '.tsx', '.jsx', '.java', '.c', '.cpp', '.h',
        '.sh', '.go', '.rs', '.rb', '.php', '.swift', '.kt', '.scala',
        '.r', '.sql', '.html', '.css', '.xml', '.yml', '.yaml'
    }

    @classmethod
    def convert(
        cls,
        text: str,
        filename: str,
        extension: Optional[str] = None
    ) -> str:
        """Convert text content to markdown based on file type.

        Args:
            text: Extracted text content
            filename: Original filename
            extension: File extension (if not in filename)

        Returns:
            Markdown formatted content
        """
        ext = extension or Path(filename).suffix.lower()

        # Route to appropriate converter
        if ext == '.pdf':
            return cls._convert_pdf(text, filename)
        elif ext in {'.csv', '.tsv'}:
            return cls._convert_csv(text, filename, ext)
        elif ext == '.json':
            return cls._convert_json(text, filename)
        elif ext == '.md':
            # Already markdown, just clean it up
            return cls._clean_markdown(text, filename)
        elif ext in cls.CODE_EXTENSIONS:
            return cls._convert_code(text, filename, ext)
        else:
            # Plain text - detect structure
            return cls._convert_plain_text(text, filename)

    @classmethod
    def _convert_pdf(cls, text: str, filename: str) -> str:
        """Convert PDF extracted text to markdown."""
        lines = []

        # Add document title
        title = Path(filename).stem.replace('-', ' ').replace('_', ' ')
        lines.append(f"# {title}\n")

        # Process content
        content_lines = text.split('\n')
        current_section = []
        in_page = False

        for line in content_lines:
            # Convert page markers to section headers
            page_match = re.match(r'^---\s*Page\s*(\d+)\s*---$', line.strip())
            if page_match:
                # Flush current section
                if current_section:
                    section_text = '\n'.join(current_section)
                    lines.append(cls._format_section(section_text))
                    current_section = []

                page_num = page_match.group(1)
                if page_num != '1':  # Don't add header for page 1
                    lines.append(f"\n---\n\n## Page {page_num}\n")
                in_page = True
                continue

            current_section.append(line)

        # Flush remaining content
        if current_section:
            section_text = '\n'.join(current_section)
            lines.append(cls._format_section(section_text))

        return '\n'.join(lines)

    @classmethod
    def _format_section(cls, text: str) -> str:
        """Format a section of text with detected structure."""
        lines = text.split('\n')
        result = []
        i = 0

        while i < len(lines):
            line = lines[i].strip()

            if not line:
                result.append('')
                i += 1
                continue

            # Detect potential headers (short lines, possibly all caps or title case)
            if cls._looks_like_header(line, lines, i):
                level = cls._determine_header_level(line, lines, i)
                header_prefix = '#' * level
                # Clean up the header text
                clean_header = cls._clean_header_text(line)
                result.append(f"\n{header_prefix} {clean_header}\n")
                i += 1
                continue

            # Detect lists
            if cls._looks_like_list_item(line):
                result.append(cls._format_list_item(line))
                i += 1
                continue

            # Regular paragraph
            result.append(line)
            i += 1

        return '\n'.join(result)

    @classmethod
    def _looks_like_header(cls, line: str, lines: List[str], index: int) -> bool:
        """Determine if a line looks like a header."""
        # Skip very long lines
        if len(line) > 80:
            return False

        # Skip lines that look like sentences (end with period and are long)
        if line.endswith('.') and len(line) > 40:
            return False

        # Check if it's all caps and reasonably short
        if line.isupper() and len(line) < 60 and len(line.split()) <= 8:
            return True

        # Check if followed by empty line and next content is longer
        if index + 1 < len(lines):
            next_line = lines[index + 1].strip()
            if not next_line and index + 2 < len(lines):
                after_empty = lines[index + 2].strip()
                if len(after_empty) > len(line) * 1.5:
                    return True

        # Common header patterns
        header_patterns = [
            r'^(Chapter|Section|Part|Introduction|Conclusion|Summary|Abstract|References|Bibliography)\s*\d*\.?',
            r'^\d+\.\s+[A-Z]',  # Numbered sections like "1. Introduction"
            r'^[A-Z][a-z]+(\s+[A-Z][a-z]+){0,4}$',  # Title case, 1-5 words
        ]

        for pattern in header_patterns:
            if re.match(pattern, line, re.IGNORECASE):
                return True

        return False

    @classmethod
    def _determine_header_level(cls, line: str, lines: List[str], index: int) -> int:
        """Determine appropriate header level (2-4)."""
        # Check for chapter/part (top level)
        if re.match(r'^(Chapter|Part)\s*\d*', line, re.IGNORECASE):
            return 2

        # Check for section numbers
        section_match = re.match(r'^(\d+)\.(\d+)?\.?(\d+)?', line)
        if section_match:
            # Count the depth
            groups = [g for g in section_match.groups() if g]
            return min(len(groups) + 1, 4)

        # All caps usually indicates major section
        if line.isupper():
            return 2

        # Default to h3 for other headers
        return 3

    @classmethod
    def _clean_header_text(cls, text: str) -> str:
        """Clean up header text."""
        # Remove trailing colons
        text = text.rstrip(':')
        # Convert all caps to title case
        if text.isupper():
            text = text.title()
        return text

    @classmethod
    def _looks_like_list_item(cls, line: str) -> bool:
        """Check if line looks like a list item."""
        patterns = [
            r'^\s*[-•*]\s+',  # Bullet points
            r'^\s*\d+[.)]\s+',  # Numbered lists
            r'^\s*[a-zA-Z][.)]\s+',  # Lettered lists
        ]
        return any(re.match(p, line) for p in patterns)

    @classmethod
    def _format_list_item(cls, line: str) -> str:
        """Format a list item as markdown."""
        # Convert various bullet styles to markdown
        line = re.sub(r'^\s*[•]\s+', '- ', line)
        # Ensure numbered lists have proper format
        line = re.sub(r'^(\s*)(\d+)\)\s+', r'\g<1>\g<2>. ', line)
        return line

    @classmethod
    def _convert_csv(cls, text: str, filename: str, ext: str) -> str:
        """Convert CSV/TSV to markdown table."""
        lines = []
        title = Path(filename).stem.replace('-', ' ').replace('_', ' ')
        lines.append(f"# {title}\n")

        rows = text.strip().split('\n')
        if not rows:
            return '\n'.join(lines)

        # Parse rows (already pipe-delimited from file processor)
        table_rows = [row.split(' | ') for row in rows]

        if not table_rows:
            return '\n'.join(lines)

        # Determine column widths for alignment
        num_cols = max(len(row) for row in table_rows)

        # Create header row
        header = table_rows[0] if table_rows else []
        header_line = '| ' + ' | '.join(header) + ' |'
        separator = '| ' + ' | '.join(['---'] * len(header)) + ' |'

        lines.append(header_line)
        lines.append(separator)

        # Add data rows
        for row in table_rows[1:]:
            # Pad row if needed
            while len(row) < num_cols:
                row.append('')
            row_line = '| ' + ' | '.join(row) + ' |'
            lines.append(row_line)

        # Add summary
        lines.append(f"\n*{len(table_rows) - 1} rows*")

        return '\n'.join(lines)

    @classmethod
    def _convert_json(cls, text: str, filename: str) -> str:
        """Convert JSON to markdown with code block."""
        lines = []
        title = Path(filename).stem.replace('-', ' ').replace('_', ' ')
        lines.append(f"# {title}\n")

        # Try to parse and add summary
        try:
            data = json.loads(text)
            if isinstance(data, dict):
                lines.append(f"*JSON object with {len(data)} keys*\n")
                # List top-level keys
                if len(data) <= 10:
                    lines.append("**Keys:** " + ', '.join(f"`{k}`" for k in data.keys()) + "\n")
            elif isinstance(data, list):
                lines.append(f"*JSON array with {len(data)} items*\n")
        except:
            pass

        # Add code block
        lines.append("```json")
        lines.append(text)
        lines.append("```")

        return '\n'.join(lines)

    @classmethod
    def _convert_code(cls, text: str, filename: str, ext: str) -> str:
        """Convert code file to markdown with syntax highlighting."""
        lines = []
        title = Path(filename).stem
        lang = cls.LANGUAGE_MAP.get(ext, 'text')

        lines.append(f"# {filename}\n")

        # Add file stats
        line_count = len(text.split('\n'))
        lines.append(f"*{lang} • {line_count} lines*\n")

        # Add code block
        lines.append(f"```{lang}")
        lines.append(text)
        lines.append("```")

        return '\n'.join(lines)

    @classmethod
    def _convert_plain_text(cls, text: str, filename: str) -> str:
        """Convert plain text to markdown with structure detection."""
        lines = []
        title = Path(filename).stem.replace('-', ' ').replace('_', ' ')
        lines.append(f"# {title}\n")

        # Format the content
        formatted = cls._format_section(text)
        lines.append(formatted)

        return '\n'.join(lines)

    @classmethod
    def _clean_markdown(cls, text: str, filename: str) -> str:
        """Clean up existing markdown file."""
        # Check if it already has a title
        lines = text.strip().split('\n')
        if lines and lines[0].startswith('# '):
            return text

        # Add title if missing
        title = Path(filename).stem.replace('-', ' ').replace('_', ' ')
        return f"# {title}\n\n{text}"


def convert_to_markdown(text: str, filename: str, extension: Optional[str] = None) -> str:
    """Convert file content to markdown.

    Args:
        text: Extracted text content
        filename: Original filename
        extension: File extension (optional)

    Returns:
        Markdown formatted content
    """
    return MarkdownConverter.convert(text, filename, extension)
