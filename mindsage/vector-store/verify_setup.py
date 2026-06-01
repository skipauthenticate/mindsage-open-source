#!/usr/bin/env python3
"""Verify MCP Vector Store setup in MindSage."""

import sys
import os

def check_import(module_name, component=None):
    """Try to import a module/component."""
    try:
        if component:
            exec(f"from {module_name} import {component}")
        else:
            __import__(module_name)
        return True
    except ImportError as e:
        return False, str(e)

def main():
    print("MCP Vector Store Setup Verification")
    print("=" * 50)

    # Add the vector-store directory to path
    script_dir = os.path.dirname(os.path.abspath(__file__))
    sys.path.insert(0, script_dir)

    checks = [
        ("Core Dependencies", [
            ("numpy", None),
            ("torch", None),
            ("sentence_transformers", "SentenceTransformer"),
            ("txtai", "Embeddings"),
        ]),
        ("HTTP Server Dependencies", [
            ("starlette", None),
            ("uvicorn", None),
            ("sse_starlette", None),
            ("httpx", None),
        ]),
        ("MCP Dependencies (optional)", [
            ("mcp", None),
            ("pydantic", None),
        ]),
        ("Vector Store Modules", [
            ("mcp_vector_store", "EmbeddingModel"),
            ("mcp_vector_store", "VectorStore"),
            ("mcp_vector_store", "chunk_text"),
            ("mcp_vector_store", "FileProcessor"),
        ]),
    ]

    all_passed = True

    for category, modules in checks:
        print(f"\n{category}:")
        for module, component in modules:
            result = check_import(module, component)
            if result is True:
                status = "OK"
            else:
                status = f"MISSING"
                if "optional" not in category.lower():
                    all_passed = False

            display = f"{module}.{component}" if component else module
            print(f"  {display}: {status}")

    print("\n" + "=" * 50)
    if all_passed:
        print("All required dependencies are installed!")
        print("\nTo start the vector store server:")
        print("  npm run vector-store:start")
        print("\nOr use Python directly:")
        print("  python vector-store/mcp_vector_store/mcp_server_http.py")
        return 0
    else:
        print("Some dependencies are missing.")
        print("\nRun: pip install -r vector-store/requirements.txt")
        return 1

if __name__ == "__main__":
    sys.exit(main())
