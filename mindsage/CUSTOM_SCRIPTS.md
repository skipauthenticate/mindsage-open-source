# Custom Scripts Guide

MindSage supports custom scripts for data import and export. This guide shows you how to use and create custom scripts.

## Using Custom Scripts

### 1. Add a Custom Script Connector

1. Click "Add Connector" in the UI
2. Select "Custom Script"
3. Enter a name for your connector
4. Paste a JSON configuration in the config field
5. Click "Add Connector"

### 2. Configuration Format

All custom scripts use JSON configuration:

```json
{
  "script": "script-name",
  "param1": "value1",
  "param2": "value2"
}
```

## Available Scripts

### ChatGPT Export

Export conversations from ChatGPT using browser automation.

**Configuration:**

```json
{
  "script": "chatgpt-export",
  "email": "your@email.com",
  "password": "yourpassword",
  "loginMethod": "openai",
  "headed": false
}
```

**Parameters:**

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `script` | string | Yes | - | Must be "chatgpt-export" |
| `email` | string | Yes | - | Your ChatGPT email address |
| `password` | string | Yes | - | Your ChatGPT password |
| `loginMethod` | string | No | "openai" | Login method: "openai" or "google" |
| `headed` | boolean | No | false | Show browser window (useful for debugging) |

**Example with Google OAuth:**

```json
{
  "script": "chatgpt-export",
  "email": "your@gmail.com",
  "password": "yourpassword",
  "loginMethod": "google",
  "headed": false
}
```

**Example with headed mode (for debugging):**

```json
{
  "script": "chatgpt-export",
  "email": "your@email.com",
  "password": "yourpassword",
  "loginMethod": "openai",
  "headed": true
}
```

**How it works:**

1. Uses Playwright to automate a Chromium browser
2. Logs into ChatGPT with your credentials
3. Saves browser session for future runs (no need to login again)
4. Fetches conversation list from sidebar
5. Extracts messages from each conversation
6. Saves as JSON to `data/exports/{connector-id}/`
7. Tracks exported IDs to avoid duplicates

**Output format:**

Each conversation is saved as a separate JSON file:

```json
{
  "id": "conversation-uuid",
  "title": "Conversation Title",
  "messages": [
    {
      "role": "user",
      "content": "User message..."
    },
    {
      "role": "assistant",
      "content": "Assistant response..."
    }
  ],
  "exportedAt": "2026-01-18T12:00:00.000Z"
}
```

## Creating Custom Scripts

### 1. Create Script File

Create a new TypeScript file in `server/scripts/`:

```typescript
// server/scripts/my-script.ts
import * as fs from 'fs';
import * as path from 'path';

const EXPORTS_DIR = process.env.EXPORTS_DIR || './data/exports';

async function main(): Promise<void> {
  // Load config from environment
  const config = loadConfig();
  
  console.log('Starting export...');
  
  // Your export logic here
  const data = await fetchData(config);
  
  // Save to exports directory
  saveData(data);
  
  console.log('Export complete!');
}

function loadConfig(): Record<string, any> {
  // Parse config from environment or file
  return {
    apiKey: process.env.API_KEY,
    // ... other config
  };
}

async function fetchData(config: Record<string, any>): Promise<any> {
  // Fetch data from your source
  return {};
}

function saveData(data: any): void {
  const filename = `export_${Date.now()}.json`;
  const filepath = path.join(EXPORTS_DIR, filename);
  fs.writeFileSync(filepath, JSON.stringify(data, null, 2));
}

main().catch((error) => {
  console.error('Export failed:', error);
  process.exit(1);
});
```

### 2. Add Script Handler

Update `server/index.ts` to handle your script:

```typescript
function runCustomScript(connectorId: string, config: Record<string, any>): void {
  const status: RunStatus = { running: true, output: [], connectorId };
  runStatuses.set(connectorId, status);

  const scriptName = config.script || 'chatgpt-export';
  
  if (scriptName === 'chatgpt-export') {
    runChatGPTExport(connectorId, config);
  } else if (scriptName === 'my-script') {
    runMyScript(connectorId, config);  // Add your handler
  } else {
    status.running = false;
    status.output.push(`Unknown script: ${scriptName}`);
    status.exitCode = 1;
  }
}

function runMyScript(connectorId: string, config: Record<string, any>): void {
  const status = runStatuses.get(connectorId);
  if (!status) return;

  const scriptPath = path.join(__dirname, 'scripts', 'my-script.js');
  const proc = spawn('node', [scriptPath], {
    cwd: ROOT_DIR,
    env: {
      ...process.env,
      EXPORTS_DIR: path.join(EXPORTS_DIR, connectorId),
      API_KEY: config.apiKey,
      // Pass other config as env vars
    },
  });

  // Handle process output and completion
  // (same as runChatGPTExport)
}
```

### 3. Use Your Script

Add a connector with your script configuration:

```json
{
  "script": "my-script",
  "apiKey": "your-api-key",
  "param1": "value1"
}
```

## Script Best Practices

### 1. Configuration

- Accept all configuration via JSON
- Use environment variables for sensitive data
- Provide sensible defaults
- Validate required parameters

### 2. Output

- Log progress to stdout
- Log errors to stderr
- Use clear, descriptive messages
- Exit with code 0 on success, non-zero on failure

### 3. Data Storage

- Save to `EXPORTS_DIR` environment variable
- Use unique filenames (timestamp, UUID, etc.)
- Save as JSON for consistency
- Track exported IDs to avoid duplicates

### 4. Error Handling

- Catch and log all errors
- Provide helpful error messages
- Clean up resources on failure
- Exit gracefully

### 5. Performance

- Show progress for long operations
- Implement rate limiting for APIs
- Use efficient data structures
- Clean up temporary files

## Example Scripts

### API Export Script

```typescript
// Export data from a REST API
{
  "script": "api-export",
  "endpoint": "https://api.example.com/data",
  "apiKey": "your-api-key",
  "format": "json"
}
```

### Database Export Script

```typescript
// Export data from a database
{
  "script": "db-export",
  "host": "localhost",
  "database": "mydb",
  "username": "user",
  "password": "pass",
  "query": "SELECT * FROM conversations"
}
```

### File Processor Script

```typescript
// Process files from a directory
{
  "script": "file-processor",
  "inputDir": "/path/to/files",
  "pattern": "*.txt",
  "transform": "uppercase"
}
```

## Troubleshooting

### Script Not Found

- Check script name in configuration
- Verify script file exists in `server/scripts/`
- Ensure script is compiled (for TypeScript)

### Script Fails to Run

- Check script logs in UI
- Verify all required parameters are provided
- Test script manually: `node server/scripts/my-script.js`
- Check file permissions

### No Output

- Ensure script logs to stdout/stderr
- Check `runStatuses` in server
- Verify script is actually running

### Data Not Saved

- Check `EXPORTS_DIR` environment variable
- Verify write permissions
- Check disk space
- Look for errors in script output

## Advanced Topics

### Incremental Sync

Track what's been exported to avoid duplicates:

```typescript
interface ExportedIds {
  ids: string[];
  lastExport: string;
}

function loadExportedIds(): ExportedIds {
  const file = path.join(EXPORTS_DIR, '.exported-ids.json');
  if (fs.existsSync(file)) {
    return JSON.parse(fs.readFileSync(file, 'utf-8'));
  }
  return { ids: [], lastExport: '' };
}

function saveExportedIds(data: ExportedIds): void {
  const file = path.join(EXPORTS_DIR, '.exported-ids.json');
  fs.writeFileSync(file, JSON.stringify(data, null, 2));
}
```

### Progress Reporting

Report progress for long operations:

```typescript
console.log(`[Progress] 0/${total} items processed`);
for (let i = 0; i < total; i++) {
  // Process item
  console.log(`[Progress] ${i + 1}/${total} items processed`);
}
```

### Authentication

Handle authentication tokens:

```typescript
interface AuthState {
  token: string;
  expiresAt: string;
}

function loadAuthState(): AuthState | null {
  const file = path.join(AUTH_DIR, 'auth-state.json');
  if (fs.existsSync(file)) {
    return JSON.parse(fs.readFileSync(file, 'utf-8'));
  }
  return null;
}

function saveAuthState(state: AuthState): void {
  const file = path.join(AUTH_DIR, 'auth-state.json');
  fs.writeFileSync(file, JSON.stringify(state, null, 2));
}
```

## Resources

- [Playwright Documentation](https://playwright.dev/)
- [Node.js Child Process](https://nodejs.org/api/child_process.html)
- [TypeScript Handbook](https://www.typescriptlang.org/docs/)

## Support

For help with custom scripts:
1. Check script logs in the UI
2. Review this guide
3. Check the ChatGPT export script as a reference
4. Open an issue on GitHub
