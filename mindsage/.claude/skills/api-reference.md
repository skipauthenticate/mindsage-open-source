# MindSage API Quick Reference

## Health Checks

```bash
# Backend
curl localhost:3003/api/stats

# Vector Store
curl localhost:8085/health

# PII Status
curl localhost:8085/health/pii

# LPRAG Status
curl localhost:8085/health/lprag
```

## Search

```bash
# Basic search
curl -X POST localhost:3003/api/vector-store/search \
  -H "Content-Type: application/json" \
  -d '{"query": "your search", "top_k": 5}'

# Enhanced search with passages
curl -X POST localhost:3003/api/vector-store/search/enhanced \
  -H "Content-Type: application/json" \
  -d '{"query": "your search", "top_k": 5}'
```

## Chat

```bash
# Non-streaming
curl -X POST localhost:3003/api/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "Hello", "history": []}'

# Check status
curl localhost:3003/api/chat/status
```

## Documents

```bash
# List documents
curl localhost:3003/api/vector-store/documents

# Add document
curl -X POST localhost:3003/api/vector-store/documents \
  -H "Content-Type: application/json" \
  -d '{"content": "...", "metadata": {"source": "test"}}'

# Index uploads
curl -X POST localhost:3003/api/vector-store/index-uploads
```

## Browser Connector

```bash
# Launch browser
curl -X POST localhost:3003/api/browser-connector/launch

# Status
curl localhost:3003/api/browser-connector/status

# List conversations
curl localhost:3003/api/browser-connector/conversations

# Close browser
curl -X POST localhost:3003/api/browser-connector/close
```

## Files

```bash
# List files
curl localhost:3003/api/files

# Upload file
curl -X POST localhost:3003/api/files/upload \
  -F "file=@/path/to/file.txt"
```

## PII

```bash
# De-anonymize
curl -X POST localhost:8085/api/pii/deanonymize \
  -H "Content-Type: application/json" \
  -d '{"text": "<PII:PERSON:abc>", "session_id": "xyz"}'

# Session info
curl localhost:8085/api/pii/session/{session_id}
```
