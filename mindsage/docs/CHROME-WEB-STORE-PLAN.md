# Publish MindSage Companion to Chrome Web Store

## Context

The MindSage Companion extension currently works as a "load unpacked" developer extension. Publishing to the Chrome Web Store makes installation easy for users and enables automatic updates. The extension relays AI session cookies from the user's desktop browser to their self-hosted MindSage server, similar to published extensions like "Get cookies.txt LOCALLY" and "Cookie Exporter".

**Current blockers for CWS submission:**
1. `<all_urls>` in `host_permissions` — CWS rejects this for extensions that don't need universal access
2. Icons are 83-byte placeholders — not real images
3. No privacy policy (required for extensions accessing cookies/user data)
4. `activeTab` permission declared but never used
5. `base.js` exists in package but isn't referenced in manifest (dead code)

## Files to Modify

| File | Change |
|------|--------|
| `extension/manifest.json` | Narrow permissions, add `optional_host_permissions` for google.com |
| `extension/popup/popup.js` | Add `chrome.permissions.request()` flow for Gemini |
| `extension/background.js` | Add permission check before cookie access |
| `extension/icons/icon16.png` | Replace placeholder with real icon |
| `extension/icons/icon48.png` | Replace placeholder with real icon |
| `extension/icons/icon128.png` | Replace placeholder with real icon |
| `extension/content/base.js` | Remove (dead code, not in manifest) |
| NEW: `extension/PRIVACY_POLICY.md` | Privacy policy document |

All extension files under: `mindsage/server/browser-connector/extension/`

## Implementation Steps

### Step 1: Narrow Manifest Permissions

**File:** `extension/manifest.json`

Replace `<all_urls>` with specific domains. Use `optional_host_permissions` for google.com (Gemini cookies live on `.google.com`, which is very broad — CWS prefers this be requested on-demand):

```json
{
  "permissions": ["storage", "cookies"],
  "host_permissions": [
    "*://*.chatgpt.com/*",
    "*://chat.openai.com/*",
    "*://*.openai.com/*",
    "*://*.claude.ai/*",
    "*://*.anthropic.com/*"
  ],
  "optional_host_permissions": [
    "*://*.google.com/*"
  ]
}
```

Changes:
- Remove `activeTab` (grep confirms it's never used — no `chrome.tabs.executeScript`, no `activeTab`-dependent API calls)
- ChatGPT + Claude domains go in `host_permissions` (always granted)
- Google domains go in `optional_host_permissions` (requested when user clicks "Connect" for Gemini)

### Step 2: Permission Request Flow in Popup

**File:** `extension/popup/popup.js`

Before relaying cookies for Gemini, check if we have the google.com host permission. If not, request it via `chrome.permissions.request()` (must be called from a user gesture context — the Connect button click handler qualifies):

```javascript
// In attachConnectHandlers(), before the relayCookies message:
const OPTIONAL_PERMISSION_SITES = {
  gemini: { origins: ['*://*.google.com/*'] }
};

async function ensureSitePermissions(site) {
  const needed = OPTIONAL_PERMISSION_SITES[site];
  if (!needed) return true; // No extra permissions needed

  const granted = await chrome.permissions.contains({ origins: needed.origins });
  if (granted) return true;

  // Request from user (shows Chrome permission prompt)
  return chrome.permissions.request({ origins: needed.origins });
}
```

Call `ensureSitePermissions(site)` at the top of the Connect button click handler. If it returns false (user denied), show a message explaining why the permission is needed and don't proceed.

### Step 3: Permission Check in Background

**File:** `extension/background.js`

Add a safety check in `relayCookies()` — before calling `chrome.cookies.getAll()`, verify we have host permissions for the domains. If not, return an error telling the user to try again from the popup (which will trigger the permission request):

```javascript
async function hasPermissionForDomain(domain) {
  const origin = `*://${domain.startsWith('.') ? '*' + domain : domain}/*`;
  return chrome.permissions.contains({ origins: [origin] });
}
```

This is a defensive check — the popup should have already requested permissions, but this prevents silent failures.

### Step 4: Generate Real Icons

Replace the 83-byte placeholder PNGs with real icons. Generate a simple MindSage brain/network icon using an HTML canvas script:

- **icon16.png** — 16x16, toolbar size
- **icon48.png** — 48x48, extensions page
- **icon128.png** — 128x128, CWS listing

Approach: Create a Node.js script using the `canvas` package (or a simple SVG-to-PNG conversion) to generate clean icons with a brain/neural-network motif in MindSage's green color scheme. The icons should be recognizable at 16x16.

Alternative: If `canvas` npm package is unavailable, create SVG files and use an online converter, or use ImageMagick to generate simple geometric icons.

### Step 5: Remove Dead Code

**File:** `extension/content/base.js` — DELETE

This file defines `window.MindSageBase` but:
- It's not listed in `manifest.json` content_scripts
- Content scripts (chatgpt.js, claude.js, gemini.js) each have their own implementations
- Unused files in the extension package may raise CWS reviewer flags

### Step 6: Create Privacy Policy

**File:** `extension/PRIVACY_POLICY.md` (also host as a web page)

Required by CWS for extensions that access cookies. Key points to cover:

- **What data is collected:** Session cookies for ChatGPT, Claude, and Gemini domains only
- **Where data is sent:** Only to the user's self-configured MindSage server URL (user enters it manually)
- **No third-party sharing:** Data never leaves the user's control
- **No analytics/tracking:** Extension collects no telemetry
- **Data storage:** Cookies are transmitted once and not stored by the extension
- **User control:** User explicitly initiates each connection; can disconnect at any time

The privacy policy URL must be provided during CWS submission. Options:
1. Host on GitHub Pages (e.g., `https://username.github.io/mindsage-companion/privacy`)
2. Host as a static page on a domain you control

### Step 7: Prepare Store Listing Assets

Required for CWS submission:

1. **Extension name:** "MindSage Companion" (already set)
2. **Short description (132 chars max):** "Sync your ChatGPT, Claude, and Gemini conversations to your self-hosted MindSage server for private, local search."
3. **Detailed description:** Explain the extension's purpose, self-hosted nature, and privacy focus
4. **Category:** Productivity
5. **Screenshots:** At least 1 screenshot of the popup UI (1280x800 or 640x400)
6. **Promotional tile (optional):** 440x280 image

### Step 8: Bump Version and Package

1. Bump version in `manifest.json` from `2.0.0` to `2.1.0` (permission model change)
2. Create a ZIP of the extension directory (excluding any dev files):
   ```bash
   cd mindsage/server/browser-connector/extension
   zip -r mindsage-companion-2.1.0.zip . -x "*.DS_Store" -x "PRIVACY_POLICY.md"
   ```

### Step 9: CWS Submission Checklist

Prerequisites:
- [ ] Chrome Web Store developer account ($5 one-time fee at https://chrome.google.com/webstore/devconsole)
- [ ] Privacy policy hosted at a public URL

Upload:
1. Go to Chrome Web Store Developer Console
2. Click "New Item" → Upload ZIP
3. Fill in store listing (name, description, screenshots, category)
4. Set privacy policy URL
5. In "Privacy practices" section, declare:
   - Cookies permission: "Used to read session cookies for AI services to enable conversation sync"
   - Storage permission: "Used to store user's server URL preference"
   - Host permissions: "Used to access cookies from specific AI service domains"
6. Submit for review (typically 1-3 business days)

## Verification

1. Load the modified extension unpacked in Chrome — verify all 3 sites still work
2. Verify ChatGPT "Connect" works without any permission prompt (host_permissions covers it)
3. Verify Gemini "Connect" triggers a Chrome permission prompt for google.com
4. After granting, verify Gemini cookies relay successfully
5. Deny the Gemini permission — verify graceful error message
6. Verify icons display correctly in Chrome toolbar, extensions page, and popup header
7. Run `zip` and verify package size is reasonable (< 100KB)
