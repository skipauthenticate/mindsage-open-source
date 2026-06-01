/**
 * Browser Connector Processor
 * Handles captured conversation data, deduplication, and indexing
 */

import * as fs from 'fs';
import * as path from 'path';
import {
  type CapturePayload,
  type CapturedConversation,
  type CapturedMessage,
  type CaptureState,
  type SupportedSite,
} from './types.js';
import { incrementCaptureCount, emitCaptureEvent } from './manager.js';
import { getVectorStoreClient, isVectorStoreAvailable } from '../vector-store-client.js';

// Paths
const DATA_DIR = path.join(process.cwd(), 'data', 'browser-connector');
const CAPTURES_DIR = path.join(DATA_DIR, 'captures');
const STATE_FILE = path.join(DATA_DIR, 'state.json');

// In-memory state
const state: CaptureState = {
  processedConversationIds: new Set(),
  lastProcessedMessageIds: new Map(),
  conversations: new Map(),
};

/**
 * Initialize processor - load state from disk
 */
export function initializeProcessor(): void {
  fs.mkdirSync(CAPTURES_DIR, { recursive: true });
  loadState();
  console.log(`[browser-connector] Processor initialized. ${state.conversations.size} conversations loaded.`);
}

/**
 * Load state from disk
 */
function loadState(): void {
  try {
    if (fs.existsSync(STATE_FILE)) {
      const data = JSON.parse(fs.readFileSync(STATE_FILE, 'utf-8'));

      state.processedConversationIds = new Set(data.processedConversationIds || []);

      if (data.lastProcessedMessageIds) {
        state.lastProcessedMessageIds = new Map(Object.entries(data.lastProcessedMessageIds));
      }

      // Load conversation files
      const files = fs.readdirSync(CAPTURES_DIR).filter(f => f.endsWith('.json'));
      for (const file of files) {
        try {
          const conversation = JSON.parse(
            fs.readFileSync(path.join(CAPTURES_DIR, file), 'utf-8')
          ) as CapturedConversation;
          state.conversations.set(conversation.id, conversation);
        } catch {
          // Skip corrupted files
        }
      }
    }
  } catch (error) {
    console.error('[browser-connector] Error loading state:', error);
  }
}

/**
 * Save state to disk
 */
function saveState(): void {
  try {
    const data = {
      processedConversationIds: Array.from(state.processedConversationIds),
      lastProcessedMessageIds: Object.fromEntries(state.lastProcessedMessageIds),
    };
    fs.writeFileSync(STATE_FILE, JSON.stringify(data, null, 2));
  } catch (error) {
    console.error('[browser-connector] Error saving state:', error);
  }
}

/**
 * Save conversation to disk
 */
function saveConversation(conversation: CapturedConversation): void {
  const filename = `${conversation.site}_${conversation.id}.json`;
  const filepath = path.join(CAPTURES_DIR, filename);
  fs.writeFileSync(filepath, JSON.stringify(conversation, null, 2));
}

/**
 * Generate a unique message ID
 */
function generateMessageId(site: SupportedSite, conversationId: string, index: number): string {
  return `${site}_${conversationId}_msg_${index}_${Date.now()}`;
}

/**
 * Process captured data from extension
 */
export async function processCapture(payload: CapturePayload): Promise<{
  success: boolean;
  conversationId: string;
  newMessages: number;
  indexed: boolean;
}> {
  const { site, conversationId, conversationUrl, title, messages, fullConversation } = payload;

  console.log(`[browser-connector] Processing capture: ${site} - ${conversationId} (${messages.length} messages)`);

  // Get or create conversation
  let conversation = state.conversations.get(conversationId);
  const isNew = !conversation;

  if (!conversation) {
    conversation = {
      id: conversationId,
      site,
      title: title || `Conversation ${conversationId.slice(0, 8)}`,
      url: conversationUrl,
      messages: [],
      createdAt: new Date().toISOString(),
      updatedAt: new Date().toISOString(),
      indexed: false,
      messageCount: 0,
    };
  }

  // Update title if provided
  if (title && title !== conversation.title) {
    conversation.title = title;
  }

  // Process messages
  let newMessages = 0;
  const existingMessageContents = new Set(
    conversation.messages.map(m => `${m.role}:${m.content.slice(0, 100)}`)
  );

  if (fullConversation) {
    // Replace all messages (used for initial load)
    const capturedMessages: CapturedMessage[] = messages.map((msg, index) => ({
      id: msg.id || generateMessageId(site, conversationId, index),
      conversationId,
      role: msg.role,
      content: msg.content,
      timestamp: msg.timestamp || new Date().toISOString(),
      site,
    }));

    newMessages = capturedMessages.length - conversation.messages.length;
    conversation.messages = capturedMessages;

  } else {
    // Append only new messages (used for incremental updates)
    for (const msg of messages) {
      const contentKey = `${msg.role}:${msg.content.slice(0, 100)}`;

      if (!existingMessageContents.has(contentKey)) {
        const capturedMessage: CapturedMessage = {
          id: msg.id || generateMessageId(site, conversationId, conversation.messages.length),
          conversationId,
          role: msg.role,
          content: msg.content,
          timestamp: msg.timestamp || new Date().toISOString(),
          site,
        };

        conversation.messages.push(capturedMessage);
        existingMessageContents.add(contentKey);
        newMessages++;
      }
    }
  }

  conversation.messageCount = conversation.messages.length;
  conversation.updatedAt = new Date().toISOString();

  // Save to disk
  state.conversations.set(conversationId, conversation);
  saveConversation(conversation);
  saveState();

  // Update capture count
  if (newMessages > 0) {
    incrementCaptureCount();
  }

  // Index to vector store
  let indexed = false;
  if (newMessages > 0 && await isVectorStoreAvailable()) {
    try {
      indexed = await indexConversation(conversation);
      conversation.indexed = indexed;
      saveConversation(conversation);
    } catch (error) {
      console.error('[browser-connector] Indexing error:', error);
    }
  }

  // Emit event
  emitCaptureEvent({
    type: isNew ? 'new_message' : 'conversation_updated',
    conversationId,
    site,
    messageCount: conversation.messageCount,
    timestamp: new Date().toISOString(),
  });

  console.log(`[browser-connector] Processed: ${newMessages} new messages, indexed: ${indexed}`);

  return {
    success: true,
    conversationId,
    newMessages,
    indexed,
  };
}

/**
 * Index conversation to vector store
 */
async function indexConversation(conversation: CapturedConversation): Promise<boolean> {
  if (!await isVectorStoreAvailable()) {
    console.log('[browser-connector] Vector store not available, skipping indexing');
    return false;
  }

  try {
    const client = getVectorStoreClient();

    // Format conversation as document text
    const documentText = formatConversationAsDocument(conversation);

    // Add to vector store with metadata
    await client.addDocument(documentText, {
      source: 'browser-connector',
      site: conversation.site,
      conversationId: conversation.id,
      title: conversation.title,
      url: conversation.url,
      messageCount: conversation.messageCount,
      capturedAt: conversation.updatedAt,
    });

    console.log(`[browser-connector] Indexed conversation: ${conversation.id}`);

    emitCaptureEvent({
      type: 'indexed',
      conversationId: conversation.id,
      site: conversation.site,
      timestamp: new Date().toISOString(),
    });

    return true;

  } catch (error) {
    console.error('[browser-connector] Failed to index conversation:', error);
    return false;
  }
}

/**
 * Format conversation as searchable document text
 */
function formatConversationAsDocument(conversation: CapturedConversation): string {
  const siteNames: Record<SupportedSite, string> = {
    chatgpt: 'ChatGPT',
    claude: 'Claude',
    gemini: 'Gemini',
  };

  const lines: string[] = [
    `# ${conversation.title}`,
    '',
    `**Source:** ${siteNames[conversation.site]} Conversation`,
    `**URL:** ${conversation.url}`,
    `**Captured:** ${conversation.updatedAt}`,
    '',
    '---',
    '',
  ];

  for (const message of conversation.messages) {
    const roleLabel = message.role === 'user' ? '**User:**' : '**Assistant:**';
    lines.push(roleLabel);
    lines.push(message.content);
    lines.push('');
  }

  return lines.join('\n');
}

/**
 * Get all captured conversations
 */
export function getConversations(options?: {
  site?: SupportedSite;
  limit?: number;
  offset?: number;
}): CapturedConversation[] {
  let conversations = Array.from(state.conversations.values());

  // Filter by site
  if (options?.site) {
    conversations = conversations.filter(c => c.site === options.site);
  }

  // Sort by updated date (newest first)
  conversations.sort((a, b) =>
    new Date(b.updatedAt).getTime() - new Date(a.updatedAt).getTime()
  );

  // Apply pagination
  if (options?.offset) {
    conversations = conversations.slice(options.offset);
  }
  if (options?.limit) {
    conversations = conversations.slice(0, options.limit);
  }

  return conversations;
}

/**
 * Get a specific conversation by ID
 */
export function getConversation(conversationId: string): CapturedConversation | null {
  return state.conversations.get(conversationId) || null;
}

/**
 * Get capture statistics
 */
export function getCaptureStats(): {
  totalConversations: number;
  totalMessages: number;
  bySite: Record<SupportedSite, { conversations: number; messages: number }>;
} {
  const stats = {
    totalConversations: 0,
    totalMessages: 0,
    bySite: {
      chatgpt: { conversations: 0, messages: 0 },
      claude: { conversations: 0, messages: 0 },
      gemini: { conversations: 0, messages: 0 },
    } as Record<SupportedSite, { conversations: number; messages: number }>,
  };

  for (const conversation of state.conversations.values()) {
    stats.totalConversations++;
    stats.totalMessages += conversation.messageCount;

    if (stats.bySite[conversation.site]) {
      stats.bySite[conversation.site].conversations++;
      stats.bySite[conversation.site].messages += conversation.messageCount;
    }
  }

  return stats;
}

/**
 * Re-index all conversations
 */
export async function reindexAll(): Promise<{ success: number; failed: number }> {
  let success = 0;
  let failed = 0;

  for (const conversation of state.conversations.values()) {
    try {
      const indexed = await indexConversation(conversation);
      if (indexed) {
        success++;
        conversation.indexed = true;
        saveConversation(conversation);
      } else {
        failed++;
      }
    } catch {
      failed++;
    }
  }

  return { success, failed };
}

/**
 * Delete a conversation
 */
export function deleteConversation(conversationId: string): boolean {
  const conversation = state.conversations.get(conversationId);
  if (!conversation) {
    return false;
  }

  // Remove from state
  state.conversations.delete(conversationId);
  state.processedConversationIds.delete(conversationId);
  state.lastProcessedMessageIds.delete(conversationId);

  // Delete file
  const filename = `${conversation.site}_${conversationId}.json`;
  const filepath = path.join(CAPTURES_DIR, filename);
  try {
    if (fs.existsSync(filepath)) {
      fs.unlinkSync(filepath);
    }
  } catch {
    // Ignore deletion errors
  }

  saveState();
  return true;
}
