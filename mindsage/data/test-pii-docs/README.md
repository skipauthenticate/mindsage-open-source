# Synthetic PII Fixture Corpus

The files in this directory are synthetic test documents for PII detection, consent filtering, anonymization, and redaction workflows.

They are intentionally realistic enough to exercise security-sensitive code paths, but they must not contain real user data. When adding fixtures:

- Use invented people, addresses, account numbers, emails, order histories, and medical details.
- Do not copy real statements, exports, records, browser captures, or messages.
- Keep this directory separate from runtime `data/` content.
- Run `npm run check:oss` before publishing changes.
