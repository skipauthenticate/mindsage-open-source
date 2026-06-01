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

for file in \
  README.md LICENSE SECURITY.md CONTRIBUTING.md CODE_OF_CONDUCT.md AGENTS.md INSTALL_FOR_AGENTS.md \
  llms.txt llms-full.txt package.json docker-compose.yml \
  docs/COMPETITIVE-ANALYSIS.md docs/OPEN-SOURCE-READINESS.md \
  mindsage/README.md mindsage/package.json mindsage/LICENSE mindsage/SECURITY.md mindsage/AGENTS.md \
  mindsage/scripts/check-open-source-ready.sh mindsage/data/test-pii-docs/README.md \
  mindsage-frontend/README.md mindsage-frontend/package.json mindsage-frontend/LICENSE mindsage-frontend/SECURITY.md mindsage-frontend/AGENTS.md
do
  require_file "$file"
done

node --input-type=module <<'NODE'
import fs from 'node:fs';
const checks = [
  ['package.json', 'mindsage-open-source'],
  ['mindsage/package.json', 'mindsage-backend'],
  ['mindsage-frontend/package.json', 'mindsage-frontend'],
];
const errors = [];
for (const [file, expectedName] of checks) {
  const pkg = JSON.parse(fs.readFileSync(file, 'utf8'));
  if (pkg.name !== expectedName) errors.push(`${file} name should be ${expectedName}`);
  if (pkg.private === true) errors.push(`${file} must not be private`);
  if (pkg.license !== 'MIT') errors.push(`${file} license must be MIT`);
  if (!pkg.description) errors.push(`${file} needs a description`);
  if (!pkg.repository?.url) errors.push(`${file} needs repository.url`);
}
if (errors.length) {
  for (const error of errors) console.error(`ERROR: ${error}`);
  process.exit(1);
}
NODE

if find mindsage/data -type f ! -path 'mindsage/data/test-pii-docs/*' -print | grep -q .; then
  find mindsage/data -type f ! -path 'mindsage/data/test-pii-docs/*' -print
  fail "runtime data present outside synthetic fixture corpus"
fi

if git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  if git ls-files | grep -Eq '(^|/)(node_modules|dist|dist-server|\.venv|models)(/|$)'; then
    git ls-files | grep -E '(^|/)(node_modules|dist|dist-server|\.venv|models)(/|$)'
    fail "generated/cache path is tracked"
  fi

  if git check-ignore -q mindsage/data/test-pii-docs/README.md; then
    fail "synthetic fixture README is ignored by git"
  fi
fi

SECRET_PATTERN='(sk-(ant-|proj-)?[A-Za-z0-9_-]{16,}|ghp_[A-Za-z0-9_]{30,}|github_pat_[A-Za-z0-9_]{40,}|xox[baprs]-[A-Za-z0-9-]{20,}|AKIA[0-9A-Z]{16}|AIza[0-9A-Za-z_-]{35}|-----BEGIN (RSA |OPENSSH |EC |DSA |)PRIVATE KEY-----)'

if command -v rg >/dev/null 2>&1; then
  if rg --pcre2 -n "$SECRET_PATTERN" \
    --glob '!**/node_modules/**' \
    --glob '!**/dist/**' \
    --glob '!**/dist-server/**' \
    --glob '!mindsage/data/test-pii-docs/**' \
    --glob '!mindsage/docs/SECURITY-AUDIT-2026.md' \
    --glob '!mindsage/docs/RED-TEAM-REPORT-2026.md' \
    .; then
    fail "secret-like token detected"
  fi
fi

(cd mindsage && npm run check:oss)

echo "Repository open-source readiness checks passed."
