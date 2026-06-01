"""File system search for unindexed content.

Provides Claude Code-style grep search over raw files that haven't been
indexed into the vector store yet. Scans uploads, imports, exports, and
browser connector conversation directories.

Zero GPU memory, CPU-only, works independently of the vector store.
"""

import os
import re
import json
import fnmatch
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional, Tuple


@dataclass
class FileMatch:
    """A single match within a file."""
    line_number: int
    text: str
    context_before: List[str] = field(default_factory=list)
    context_after: List[str] = field(default_factory=list)


@dataclass
class FileSearchResult:
    """Search result from file system search."""
    filename: str
    path: str
    matches: List[FileMatch]
    source: str  # "uploads", "imports", "exports", "conversations"
    file_size: int = 0


# File extensions we can search as text
TEXT_EXTENSIONS = {
    '.txt', '.md', '.csv', '.json', '.jsonl', '.xml', '.html', '.htm',
    '.log', '.yaml', '.yml', '.toml', '.ini', '.cfg', '.conf',
    '.py', '.js', '.ts', '.sh', '.bash', '.sql',
    '.rst', '.tex', '.org', '.ndjson',
}

# Max file size to search (10MB)
MAX_FILE_SIZE = 10 * 1024 * 1024

# Max content cache size (50MB)
MAX_CACHE_SIZE = 50 * 1024 * 1024


class FileContentCache:
    """LRU cache for file contents with mtime invalidation."""

    def __init__(self, max_size_bytes: int = MAX_CACHE_SIZE):
        self._cache: OrderedDict[str, Tuple[str, float, int]] = OrderedDict()  # path -> (content, mtime, size)
        self._current_size = 0
        self._max_size = max_size_bytes

    def get(self, path: str) -> Optional[str]:
        """Get cached content if file hasn't changed."""
        if path not in self._cache:
            return None

        content, cached_mtime, size = self._cache[path]
        try:
            current_mtime = os.path.getmtime(path)
            if current_mtime != cached_mtime:
                # File changed, invalidate
                del self._cache[path]
                self._current_size -= size
                return None
        except OSError:
            del self._cache[path]
            self._current_size -= size
            return None

        # Move to end (most recently used)
        self._cache.move_to_end(path)
        return content

    def put(self, path: str, content: str, mtime: float):
        """Cache file content."""
        size = len(content.encode('utf-8', errors='replace'))

        # Don't cache files larger than half the max cache
        if size > self._max_size // 2:
            return

        # Evict old entries if needed
        while self._current_size + size > self._max_size and self._cache:
            _, (_, _, old_size) = self._cache.popitem(last=False)
            self._current_size -= old_size

        self._cache[path] = (content, mtime, size)
        self._current_size += size


class FileSearcher:
    """Search through raw files on the filesystem.

    Provides grep-like search for files that may not yet be indexed
    in the vector store. Searches text files, JSON conversations,
    and other supported formats.
    """

    def __init__(
        self,
        data_dir: str = "data",
        max_workers: int = 4,
        context_lines: int = 2
    ):
        self.data_dir = data_dir
        self.max_workers = max_workers
        self.context_lines = context_lines
        self._cache = FileContentCache()

        # Map directory names to paths
        self._directories = {
            "uploads": os.path.join(data_dir, "uploads"),
            "imports": os.path.join(data_dir, "imports"),
            "exports": os.path.join(data_dir, "exports"),
            "conversations": os.path.join(data_dir, "browser-connector", "conversations"),
        }

    def search(
        self,
        query: str,
        directories: Optional[List[str]] = None,
        max_results: int = 20,
        case_sensitive: bool = False
    ) -> List[FileSearchResult]:
        """
        Search for text across files in specified directories.

        Args:
            query: Search string (supports basic regex)
            directories: List of directory names to search ("uploads", "imports", etc.)
                        If None, searches all directories.
            max_results: Maximum number of file results to return
            case_sensitive: Whether search is case-sensitive

        Returns:
            List of FileSearchResult objects with matches
        """
        start_time = time.monotonic()

        if not directories:
            directories = list(self._directories.keys())

        # Compile search pattern
        flags = 0 if case_sensitive else re.IGNORECASE
        try:
            pattern = re.compile(re.escape(query), flags)
        except re.error:
            # If query has special chars, escape it
            pattern = re.compile(re.escape(query), flags)

        # Collect files to search
        files_to_search = []
        for dir_name in directories:
            dir_path = self._directories.get(dir_name)
            if not dir_path or not os.path.isdir(dir_path):
                continue
            files_to_search.extend(self._collect_files(dir_path, dir_name))

        if not files_to_search:
            return []

        # Search files in parallel
        results = []
        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            futures = {
                executor.submit(self._search_file, filepath, source, pattern): (filepath, source)
                for filepath, source in files_to_search
            }

            for future in as_completed(futures):
                try:
                    result = future.result()
                    if result and result.matches:
                        results.append(result)
                        if len(results) >= max_results:
                            break
                except Exception:
                    pass

        # Sort by number of matches (most relevant first)
        results.sort(key=lambda r: len(r.matches), reverse=True)
        return results[:max_results]

    def search_filenames(
        self,
        pattern: str,
        directories: Optional[List[str]] = None
    ) -> List[Dict[str, str]]:
        """
        Search for files by filename pattern (glob).

        Args:
            pattern: Glob pattern (e.g., "*.pdf", "report*")
            directories: Directories to search

        Returns:
            List of dicts with filename, path, source
        """
        if not directories:
            directories = list(self._directories.keys())

        matches = []
        for dir_name in directories:
            dir_path = self._directories.get(dir_name)
            if not dir_path or not os.path.isdir(dir_path):
                continue

            for entry in os.scandir(dir_path):
                if entry.is_file() and fnmatch.fnmatch(entry.name, pattern):
                    matches.append({
                        "filename": entry.name,
                        "path": entry.path,
                        "source": dir_name,
                        "size": entry.stat().st_size
                    })

        return matches

    def _collect_files(self, dir_path: str, source: str) -> List[Tuple[str, str]]:
        """Collect searchable files from a directory."""
        files = []
        try:
            for entry in os.scandir(dir_path):
                if entry.is_file():
                    # Check file size
                    try:
                        if entry.stat().st_size > MAX_FILE_SIZE:
                            continue
                    except OSError:
                        continue

                    # Check if searchable
                    if self._is_searchable(entry.path):
                        files.append((entry.path, source))

                elif entry.is_dir() and source == "conversations":
                    # Recurse into conversation subdirectories
                    for sub_entry in os.scandir(entry.path):
                        if sub_entry.is_file() and self._is_searchable(sub_entry.path):
                            try:
                                if sub_entry.stat().st_size <= MAX_FILE_SIZE:
                                    files.append((sub_entry.path, source))
                            except OSError:
                                continue
        except OSError:
            pass
        return files

    def _is_searchable(self, filepath: str) -> bool:
        """Check if a file can be searched as text."""
        _, ext = os.path.splitext(filepath.lower())
        if ext in TEXT_EXTENSIONS:
            return True

        # Check first bytes for binary content
        try:
            with open(filepath, 'rb') as f:
                chunk = f.read(512)
                if b'\x00' in chunk:
                    return False  # Binary file
                return True
        except OSError:
            return False

    def _search_file(
        self,
        filepath: str,
        source: str,
        pattern: re.Pattern
    ) -> Optional[FileSearchResult]:
        """Search a single file for matches."""
        content = self._read_file_content(filepath)
        if not content:
            return None

        lines = content.split('\n')
        matches = []

        for i, line in enumerate(lines):
            if pattern.search(line):
                # Get context lines
                context_before = lines[max(0, i - self.context_lines):i]
                context_after = lines[i + 1:i + 1 + self.context_lines]

                matches.append(FileMatch(
                    line_number=i + 1,
                    text=line.strip(),
                    context_before=[l.strip() for l in context_before],
                    context_after=[l.strip() for l in context_after]
                ))

                # Cap matches per file
                if len(matches) >= 10:
                    break

        if not matches:
            return None

        try:
            file_size = os.path.getsize(filepath)
        except OSError:
            file_size = 0

        return FileSearchResult(
            filename=os.path.basename(filepath),
            path=filepath,
            matches=matches,
            source=source,
            file_size=file_size
        )

    def _read_file_content(self, filepath: str) -> Optional[str]:
        """Read file content with caching and JSON parsing."""
        # Check cache first
        cached = self._cache.get(filepath)
        if cached is not None:
            return cached

        try:
            mtime = os.path.getmtime(filepath)

            _, ext = os.path.splitext(filepath.lower())

            if ext == '.json':
                content = self._read_json_content(filepath)
            else:
                with open(filepath, 'r', encoding='utf-8', errors='replace') as f:
                    content = f.read()

            if content:
                self._cache.put(filepath, content, mtime)
            return content

        except (OSError, UnicodeDecodeError):
            return None

    def _read_json_content(self, filepath: str) -> Optional[str]:
        """Extract searchable text from JSON files (conversations, exports)."""
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError):
            # Fall back to raw text
            try:
                with open(filepath, 'r', encoding='utf-8', errors='replace') as f:
                    return f.read()
            except OSError:
                return None

        # Handle ChatGPT conversation format
        if isinstance(data, dict):
            parts = []
            if 'title' in data:
                parts.append(f"Title: {data['title']}")

            # ChatGPT conversation messages
            if 'mapping' in data:
                for node in data['mapping'].values():
                    msg = node.get('message')
                    if msg and msg.get('content', {}).get('parts'):
                        role = msg.get('author', {}).get('role', 'unknown')
                        text = ' '.join(str(p) for p in msg['content']['parts'] if isinstance(p, str))
                        if text.strip():
                            parts.append(f"{role}: {text}")

            # Generic messages array
            elif 'messages' in data and isinstance(data['messages'], list):
                for msg in data['messages']:
                    if isinstance(msg, dict):
                        role = msg.get('role', msg.get('sender', 'unknown'))
                        content = msg.get('content', msg.get('text', ''))
                        if content:
                            parts.append(f"{role}: {content}")

            if parts:
                return '\n'.join(parts)

        # Handle array of objects
        elif isinstance(data, list):
            parts = []
            for item in data[:100]:  # Limit to first 100 items
                if isinstance(item, dict):
                    # Try common text fields
                    for key in ['text', 'content', 'message', 'body', 'title', 'description']:
                        if key in item and isinstance(item[key], str):
                            parts.append(item[key])
                            break
                elif isinstance(item, str):
                    parts.append(item)
            if parts:
                return '\n'.join(parts)

        # Fallback: dump as string
        return json.dumps(data, indent=2, ensure_ascii=False)
