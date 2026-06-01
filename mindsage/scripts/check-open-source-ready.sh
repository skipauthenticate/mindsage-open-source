#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

fail() {
  echo "ERROR: $*" >&2
  exit 1
}

require_file() {
  [ -f "$1" ] || fail "missing required file: $1"
}

require_file README.md
require_file LICENSE
require_file SECURITY.md
require_file CONTRIBUTING.md
require_file CODE_OF_CONDUCT.md
require_file AGENTS.md
require_file INSTALL_FOR_AGENTS.md
require_file llms.txt
require_file .env.example
require_file docs/COMPETITIVE-ANALYSIS.md

node --input-type=module <<'NODE'
import fs from 'node:fs';
const pkg = JSON.parse(fs.readFileSync('package.json', 'utf8'));
const errors = [];
if (pkg.private === true) errors.push('package.json must not be private');
if (pkg.license !== 'MIT') errors.push('package.json license must be MIT');
if (!pkg.description) errors.push('package.json needs a description');
if (!pkg.repository?.url) errors.push('package.json needs repository.url');
for (const script of ['build', 'test', 'check:oss']) {
  if (!pkg.scripts?.[script]) errors.push(`package.json missing script: ${script}`);
}
if (errors.length) {
  for (const error of errors) console.error(`ERROR: ${error}`);
  process.exit(1);
}
NODE

if git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  if git ls-files | grep -Eq '(^|/)\.env$|\.pem$|\.key$|llm-config\.json$|connectors\.json$'; then
    git ls-files | grep -E '(^|/)\.env$|\.pem$|\.key$|llm-config\.json$|connectors\.json$'
    fail "tracked secret-bearing file detected"
  fi

  if git ls-files data | grep -Ev '^data/test-pii-docs/|^$' >/tmp/mindsage-oss-data-files.txt; then
    cat /tmp/mindsage-oss-data-files.txt
    fail "tracked runtime data outside data/test-pii-docs"
  fi
fi

if [ -d data/test-pii-docs ]; then
  require_file data/test-pii-docs/README.md
  if git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    git check-ignore -q data/test-pii-docs/README.md && fail "data/test-pii-docs/README.md is ignored by git"
  fi
fi

SECRET_PATTERN='(sk-(ant-|proj-)?[A-Za-z0-9_-]{16,}|ghp_[A-Za-z0-9_]{30,}|github_pat_[A-Za-z0-9_]{40,}|xox[baprs]-[A-Za-z0-9-]{20,}|AKIA[0-9A-Z]{16}|AIza[0-9A-Za-z_-]{35}|-----BEGIN (RSA |OPENSSH |EC |DSA |)PRIVATE KEY-----)'

if command -v rg >/dev/null 2>&1; then
  if rg --pcre2 -n "$SECRET_PATTERN" \
    --glob '!node_modules/**' \
    --glob '!dist/**' \
    --glob '!dist-server/**' \
    --glob '!data/test-pii-docs/**' \
    --glob '!docs/SECURITY-AUDIT-2026.md' \
    --glob '!docs/RED-TEAM-REPORT-2026.md' \
    .; then
    fail "secret-like token detected"
  fi
fi

echo "Open-source readiness checks passed."
