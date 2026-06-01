#!/usr/bin/env python3
"""Download embedding models for MCP Vector Store."""

import os
import sys


def download_embedding_models(cache_dir: str, device: str):
    """Download embedding models based on hardware."""
    from sentence_transformers import SentenceTransformer

    # Model selection based on hardware
    models_to_download = []

    if device == "cuda":
        # Download the better quality model for GPU
        models_to_download.append({
            "name": "sentence-transformers/all-mpnet-base-v2",
            "description": "High-quality embeddings (768 dims) - optimized for GPU"
        })
    else:
        # Download the faster model for CPU
        models_to_download.append({
            "name": "sentence-transformers/all-MiniLM-L6-v2",
            "description": "Fast embeddings (384 dims) - optimized for CPU"
        })

    # Download models
    for model_info in models_to_download:
        model_name = model_info["name"]
        description = model_info["description"]

        print(f"Downloading: {model_name}")
        print(f"Description: {description}")
        print("-" * 40)

        try:
            model = SentenceTransformer(
                model_name,
                cache_folder=cache_dir,
                device=device
            )
            embedding_dim = model.get_sentence_embedding_dimension()
            print(f"Success! Embedding dimension: {embedding_dim}")
            print()
        except Exception as e:
            print(f"Error downloading {model_name}: {e}")
            sys.exit(1)


def download_spacy_model():
    """Download spaCy model for NER (used by PII protection and entity extraction)."""
    print("Checking spaCy model...")
    print("-" * 40)

    try:
        import spacy
        try:
            nlp = spacy.load("en_core_web_sm")
            print("spaCy en_core_web_sm already installed")
        except OSError:
            print("Downloading spaCy en_core_web_sm model...")
            spacy.cli.download("en_core_web_sm")
            print("Success! spaCy model installed")
    except ImportError:
        print("Warning: spaCy not installed, skipping NER model download")
        print("Install with: pip install spacy")
        print("Then run: python -m spacy download en_core_web_sm")

    print()


def download_media_models():
    """Download models for audio transcription and image captioning."""
    print("Downloading media processing models...")
    print("-" * 40)

    # Whisper for audio transcription
    try:
        from transformers import pipeline as hf_pipeline
        print("Downloading Whisper (openai/whisper-tiny.en) for audio transcription...")
        pipe = hf_pipeline("automatic-speech-recognition", model="openai/whisper-tiny.en")
        del pipe
        print("Success! Whisper model downloaded")
    except Exception as e:
        print(f"Warning: Could not download Whisper model: {e}")
        print("Audio transcription will download the model on first use")

    print()

    # BLIP for image captioning
    try:
        from transformers import pipeline as hf_pipeline
        print("Downloading BLIP (Salesforce/blip-image-captioning-base) for image captioning...")
        pipe = hf_pipeline("image-to-text", model="Salesforce/blip-image-captioning-base")
        del pipe
        print("Success! BLIP model downloaded")
    except Exception as e:
        print(f"Warning: Could not download BLIP model: {e}")
        print("Image captioning will download the model on first use")

    print()


def main():
    """Download embedding models based on hardware."""
    print("MCP Vector Store - Model Downloader")
    print("=" * 50)

    try:
        import torch
        from sentence_transformers import SentenceTransformer
    except ImportError as e:
        print(f"Error: Required packages not installed.")
        print("Run: pip install -r vector-store/requirements.txt")
        sys.exit(1)

    # Determine device
    device = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"Detected device: {device}")

    # Create cache directory
    cache_dir = "./vector-store/models"
    os.makedirs(cache_dir, exist_ok=True)
    print(f"Cache directory: {cache_dir}")
    print()

    # Download embedding models
    print("=" * 50)
    print("Step 1: Downloading Embedding Models")
    print("=" * 50)
    download_embedding_models(cache_dir, device)

    # Download spaCy model for NER
    print("=" * 50)
    print("Step 2: Checking spaCy NER Model")
    print("=" * 50)
    download_spacy_model()

    # Download media processing models (Whisper + BLIP)
    print("=" * 50)
    print("Step 3: Downloading Media Models (Audio & Image)")
    print("=" * 50)
    download_media_models()

    print("=" * 50)
    print("Model download complete!")
    print()
    print("Downloaded models:")
    print("  - Embedding model (for semantic search)")
    print("  - spaCy en_core_web_sm (for entity extraction)")
    print("  - Whisper tiny.en (for audio transcription)")
    print("  - BLIP base (for image captioning)")
    print()
    print("To start the vector store server, run:")
    print("  npm run vector-store:start")
    print()
    print("Or use Python directly:")
    print("  python vector-store/mcp_vector_store/mcp_server_http.py")


if __name__ == "__main__":
    main()
