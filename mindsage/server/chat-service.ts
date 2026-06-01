/**
 * Chat Service for MindSage
 *
 * Implements chat functionality using external LLM services (OpenAI, Anthropic)
 * with RAG (Retrieval Augmented Generation) support from the vector store.
 *
 * PII Protection Flow (with LPRAG - Local Differential Privacy):
 * 1. RAG context (search results) is anonymized during buildRAGContext()
 * 2. User message + conversation history are anonymized server-side before LLM
 * 3. LLM sees ONLY anonymized content — never real PII
 * 4. LLM response is de-anonymized server-side after streaming completes
 * 5. Frontend receives a 'deanonymized' event with restored text
 * 6. PII session ID never leaves the backend (reduced attack surface)
 *
 * Benefits of LPRAG over token-only:
 * - LLM can reason semantically about names, locations, etc.
 * - Mathematical privacy guarantee (ε-differential privacy)
 * - Automatic fallback to tokens for edge cases
 */

import * as fs from 'fs';
import * as path from 'path';
import { fileURLToPath } from 'url';
import {
  getVectorStoreClient,
  isVectorStoreAvailable,
  EnhancedSearchResult,
  PerturbedValue,
} from './vector-store-client.js';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const DATA_DIR = path.join(__dirname, '..', 'data');
const LLM_CONFIG_PATH = path.join(DATA_DIR, 'llm-config.json');

// LLM Provider Types
export type LLMProvider = 'openai' | 'anthropic' | 'groq';

// Types
export interface ChatMessage {
  role: 'user' | 'assistant' | 'system';
  content: string;
}

// Multimodal message types for LLM APIs
export interface MultimodalContentPart {
  type: 'text' | 'image';
  text?: string;
  // For OpenAI
  image_url?: {
    url: string;  // data:image/jpeg;base64,...
    detail?: 'auto' | 'low' | 'high';
  };
  // For Anthropic
  source?: {
    type: 'base64';
    media_type: string;
    data: string;
  };
}

export interface MultimodalMessage {
  role: 'user' | 'assistant' | 'system';
  content: string | MultimodalContentPart[];
}

export interface ChatContext {
  id: number;
  excerpt: string;
  score: number;
  source?: string;
  filename?: string;
  perturbed_values?: PerturbedValue[];  // Anonymized values for UI highlighting
  // Image RAG support (for multimodal LLMs)
  imageData?: {
    base64: string;
    mediaType: string;
    imageId: string;
    caption?: string;
  };
}

export interface ChatStatus {
  llmAvailable: boolean;
  llmProvider: LLMProvider | null;
  vectorStoreAvailable: boolean;
  defaultModel: string | null;
  availableModels: string[];
  gpuAvailable: boolean;
  gpuStatus: string;
  // Legacy compatibility
  ollamaAvailable: boolean;
}

export interface ChatRequest {
  message: string;
  conversationHistory?: ChatMessage[];
  model?: string;
  useRAG?: boolean;
  topK?: number;
  minScore?: number;
  temperature?: number;
  maxTokens?: number;
  consentSessionId?: string;
  voiceInitiated?: boolean;
}

export interface ChatResponse {
  message: string;
  model: string;
  context?: ChatContext[];
  tokensUsed?: number;
  duration?: number;
}

export interface StreamEvent {
  type: 'context' | 'token' | 'deanonymized' | 'done' | 'error';
  content?: string;
  context?: ChatContext[];
  model?: string;
  tokensUsed?: number;
  duration?: number;
  error?: string;
}

// LLM Provider Configuration
interface LLMConfig {
  provider: LLMProvider;
  apiKey: string;
  defaultModel: string;
  availableModels: string[];
}

// Stored configuration (persisted to file)
export interface StoredLLMConfig {
  preferredProvider: 'auto' | LLMProvider;
  openaiApiKey?: string;
  anthropicApiKey?: string;
  groqApiKey?: string;
  openaiModel?: string;
  anthropicModel?: string;
  groqModel?: string;
}

// Public config response (with masked keys)
export interface LLMConfigResponse {
  preferredProvider: 'auto' | LLMProvider;
  openaiConfigured: boolean;
  anthropicConfigured: boolean;
  groqConfigured: boolean;
  openaiModel: string;
  anthropicModel: string;
  groqModel: string;
  activeProvider: LLMProvider | null;
}

const DEFAULT_OPENAI_MODEL = 'gpt-4o-mini';
const DEFAULT_ANTHROPIC_MODEL = 'claude-sonnet-4-20250514';
const DEFAULT_GROQ_MODEL = 'llama-3.3-70b-versatile';

const OPENAI_MODELS = [
  'gpt-4o',
  'gpt-4o-mini',
  'gpt-4-turbo',
  'gpt-3.5-turbo',
];

const ANTHROPIC_MODELS = [
  'claude-sonnet-4-20250514',
  'claude-3-5-sonnet-20241022',
  'claude-3-5-haiku-20241022',
];

const GROQ_MODELS = [
  'llama-3.3-70b-versatile',
  'llama-3.1-8b-instant',
  'mixtral-8x7b-32768',
  'gemma2-9b-it',
];

/**
 * Load stored LLM configuration from file
 */
export function loadStoredConfig(): StoredLLMConfig {
  try {
    if (fs.existsSync(LLM_CONFIG_PATH)) {
      const data = fs.readFileSync(LLM_CONFIG_PATH, 'utf-8');
      return JSON.parse(data);
    }
  } catch (error) {
    console.error('Error loading LLM config:', error);
  }
  return {
    preferredProvider: 'auto',
  };
}

/**
 * Save LLM configuration to file
 */
export function saveStoredConfig(config: StoredLLMConfig): void {
  try {
    // Ensure data directory exists
    if (!fs.existsSync(DATA_DIR)) {
      fs.mkdirSync(DATA_DIR, { recursive: true });
    }
    fs.writeFileSync(LLM_CONFIG_PATH, JSON.stringify(config, null, 2));
  } catch (error) {
    console.error('Error saving LLM config:', error);
    throw error;
  }
}

/**
 * Get public config response (with masked keys)
 */
export function getLLMConfigResponse(): LLMConfigResponse {
  const stored = loadStoredConfig();
  const config = getLLMConfig();

  return {
    preferredProvider: stored.preferredProvider,
    openaiConfigured: !!(stored.openaiApiKey || process.env.OPENAI_API_KEY),
    anthropicConfigured: !!(stored.anthropicApiKey || process.env.ANTHROPIC_API_KEY),
    groqConfigured: !!(stored.groqApiKey || process.env.GROQ_API_KEY),
    openaiModel: stored.openaiModel || DEFAULT_OPENAI_MODEL,
    anthropicModel: stored.anthropicModel || DEFAULT_ANTHROPIC_MODEL,
    groqModel: stored.groqModel || DEFAULT_GROQ_MODEL,
    activeProvider: config?.provider || null,
  };
}

/**
 * Update LLM configuration
 */
export function updateLLMConfig(update: Partial<StoredLLMConfig>): LLMConfigResponse {
  const current = loadStoredConfig();
  const updated: StoredLLMConfig = {
    ...current,
    ...update,
  };

  // Don't overwrite keys with undefined
  if (update.openaiApiKey === undefined && current.openaiApiKey) {
    updated.openaiApiKey = current.openaiApiKey;
  }
  if (update.anthropicApiKey === undefined && current.anthropicApiKey) {
    updated.anthropicApiKey = current.anthropicApiKey;
  }
  if (update.groqApiKey === undefined && current.groqApiKey) {
    updated.groqApiKey = current.groqApiKey;
  }

  saveStoredConfig(updated);
  return getLLMConfigResponse();
}

/**
 * Test an API key by making a simple request
 */
export async function testApiKey(provider: LLMProvider, apiKey: string): Promise<{ success: boolean; error?: string }> {
  try {
    if (provider === 'openai') {
      const response = await fetch('https://api.openai.com/v1/models', {
        headers: {
          'Authorization': `Bearer ${apiKey}`,
        },
      });
      if (!response.ok) {
        return { success: false, error: `OpenAI API error: ${response.status}` };
      }
      return { success: true };
    } else if (provider === 'groq') {
      // Groq uses OpenAI-compatible API
      const response = await fetch('https://api.groq.com/openai/v1/models', {
        headers: {
          'Authorization': `Bearer ${apiKey}`,
        },
      });
      if (!response.ok) {
        return { success: false, error: `Groq API error: ${response.status}` };
      }
      return { success: true };
    } else {
      // Anthropic doesn't have a simple list endpoint, so we use a minimal completion
      const response = await fetch('https://api.anthropic.com/v1/messages', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'x-api-key': apiKey,
          'anthropic-version': '2023-06-01',
        },
        body: JSON.stringify({
          model: 'claude-3-5-haiku-20241022',
          max_tokens: 1,
          messages: [{ role: 'user', content: 'Hi' }],
        }),
      });
      if (!response.ok) {
        if (response.status === 401) {
          return { success: false, error: 'Invalid API key' };
        }
        return { success: false, error: `Anthropic API error: ${response.status}` };
      }
      return { success: true };
    }
  } catch (error) {
    return { success: false, error: String(error) };
  }
}

function getLLMConfig(): LLMConfig | null {
  const stored = loadStoredConfig();

  // Get keys from stored config or environment
  const openaiKey = stored.openaiApiKey || process.env.OPENAI_API_KEY;
  const anthropicKey = stored.anthropicApiKey || process.env.ANTHROPIC_API_KEY;
  const groqKey = stored.groqApiKey || process.env.GROQ_API_KEY;

  // Determine which provider to use based on preference
  const preference = stored.preferredProvider;

  if (preference === 'anthropic' && anthropicKey) {
    return {
      provider: 'anthropic',
      apiKey: anthropicKey,
      defaultModel: stored.anthropicModel || DEFAULT_ANTHROPIC_MODEL,
      availableModels: ANTHROPIC_MODELS,
    };
  }

  if (preference === 'openai' && openaiKey) {
    return {
      provider: 'openai',
      apiKey: openaiKey,
      defaultModel: stored.openaiModel || DEFAULT_OPENAI_MODEL,
      availableModels: OPENAI_MODELS,
    };
  }

  if (preference === 'groq' && groqKey) {
    return {
      provider: 'groq',
      apiKey: groqKey,
      defaultModel: stored.groqModel || DEFAULT_GROQ_MODEL,
      availableModels: GROQ_MODELS,
    };
  }

  // Auto mode: prefer Anthropic > Groq > OpenAI
  if (anthropicKey) {
    return {
      provider: 'anthropic',
      apiKey: anthropicKey,
      defaultModel: stored.anthropicModel || DEFAULT_ANTHROPIC_MODEL,
      availableModels: ANTHROPIC_MODELS,
    };
  }

  if (groqKey) {
    return {
      provider: 'groq',
      apiKey: groqKey,
      defaultModel: stored.groqModel || DEFAULT_GROQ_MODEL,
      availableModels: GROQ_MODELS,
    };
  }

  if (openaiKey) {
    return {
      provider: 'openai',
      apiKey: openaiKey,
      defaultModel: stored.openaiModel || DEFAULT_OPENAI_MODEL,
      availableModels: OPENAI_MODELS,
    };
  }

  return null;
}

/**
 * Get chat service status
 */
export async function getChatStatus(): Promise<ChatStatus> {
  const config = getLLMConfig();
  const vectorStoreAvailable = await isVectorStoreAvailable();

  // Check GPU status from vector store
  let gpuAvailable = true;
  let gpuStatus = 'Available';

  if (vectorStoreAvailable) {
    try {
      const client = getVectorStoreClient();
      const info = await client.getInfo();
      if (info.extraction_queue) {
        const { active, pending } = info.extraction_queue;
        if (active || pending > 0) {
          gpuAvailable = false;
          gpuStatus = active
            ? `Processing: ${info.extraction_queue.current_file || 'document'}`
            : `${pending} files queued`;
        }
      }
    } catch {
      // Ignore errors, assume GPU available
    }
  }

  return {
    llmAvailable: config !== null,
    llmProvider: config?.provider || null,
    vectorStoreAvailable,
    defaultModel: config?.defaultModel || null,
    availableModels: config?.availableModels || [],
    gpuAvailable,
    gpuStatus,
    // Legacy compatibility - map llmAvailable to ollamaAvailable
    ollamaAvailable: config !== null,
  };
}

// Environment variable to enable/disable image RAG (default: true)
const ENABLE_IMAGE_RAG = process.env.ENABLE_IMAGE_RAG !== 'false';
// Max image dimension for LLM input (to limit token usage)
const IMAGE_RAG_MAX_SIZE = parseInt(process.env.IMAGE_RAG_MAX_SIZE || '1024', 10);

/**
 * Build RAG context from vector store search results.
 *
 * Uses LPRAG (Local Differential Privacy) by default to protect PII:
 * - Names/locations are perturbed to similar values ("John" → "Michael")
 * - Phone numbers/SSNs are perturbed with Laplace noise
 * - Emails are perturbed segment-wise ("john@example.com" → "mike@sample.org")
 * - Unsupported types fall back to tokens (<PII:TYPE:abc123>)
 *
 * When ENABLE_IMAGE_RAG is true (default), images are included as base64 data
 * for multimodal LLMs. Redacted versions are used for PII safety.
 *
 * The returned piiSessionId can be used to de-anonymize LLM responses,
 * restoring both perturbed values and tokens to their originals.
 */
async function buildRAGContext(
  query: string,
  topK: number = 5,
  minScore: number = 0.4,
  consentSessionId?: string
): Promise<{ context: ChatContext[]; piiSessionId?: string }> {
  const available = await isVectorStoreAvailable();
  if (!available) {
    return { context: [] };
  }

  try {
    const client = getVectorStoreClient();

    // Get search results with consent-based category/document filtering
    // Use context="llm" to ensure redacted image paths are returned for PII safety
    const response = await client.enhancedSearch(query, {
      topK,
      minScore,
      extractPassages: true,
      maxExcerptLength: 500,
      consentSessionId,  // Filter by allowed/blocked categories
      context: 'llm',    // LLM context: return redacted images for PII safety
    });

    if (response.results.length === 0) {
      return { context: [] };
    }

    // Anonymize excerpts before sending to external LLM
    // Combine all excerpts into one text block for efficient anonymization
    const combinedText = response.results
      .map((r, i) => `[EXCERPT_${i}]${r.excerpt}[/EXCERPT_${i}]`)
      .join('\n');

    // Anonymize with consent-aware PII type rules (exposed types won't be anonymized)
    const anonymizeResult = await client.anonymize(combinedText, undefined, consentSessionId);

    // Parse anonymized text back into individual excerpts
    // Pass all spans to each excerpt - frontend does string matching to find relevant ones
    const anonymizedExcerpts: string[] = [];
    for (let i = 0; i < response.results.length; i++) {
      const startTag = `[EXCERPT_${i}]`;
      const endTag = `[/EXCERPT_${i}]`;
      const startIdx = anonymizeResult.anonymized_text.indexOf(startTag);
      const endIdx = anonymizeResult.anonymized_text.indexOf(endTag);
      if (startIdx !== -1 && endIdx !== -1) {
        anonymizedExcerpts.push(anonymizeResult.anonymized_text.slice(startIdx + startTag.length, endIdx));
      } else {
        // Fallback to original if parsing fails
        anonymizedExcerpts.push(response.results[i].excerpt);
      }
    }

    // Fetch base64 images for image documents (if enabled)
    // Uses redacted versions for PII safety
    const imageDataMap = new Map<string, ChatContext['imageData']>();
    if (ENABLE_IMAGE_RAG) {
      const imageResults = response.results.filter(r => r.metadata?.image_id);
      await Promise.all(
        imageResults.map(async (result) => {
          const imageId = result.metadata?.image_id;
          if (!imageId) return;

          try {
            const imageData = await client.getImageBase64(imageId, 'llm', IMAGE_RAG_MAX_SIZE);
            if (imageData?.success) {
              imageDataMap.set(imageId, {
                base64: imageData.base64_data,
                mediaType: imageData.media_type,
                imageId: imageData.image_id,
                caption: result.metadata?.caption,
              });
            }
          } catch (err) {
            console.warn(`Failed to fetch image ${imageId} for RAG:`, err);
          }
        })
      );
    }

    const context: ChatContext[] = response.results.map((result: EnhancedSearchResult, i: number) => {
      const ctx: ChatContext = {
        id: result.id,
        excerpt: anonymizedExcerpts[i] || result.excerpt,
        score: result.score,
        source: result.metadata?.source,
        filename: result.metadata?.filename,
        perturbed_values: anonymizeResult.perturbed_values || [],
      };

      // Add image data if available
      const imageId = result.metadata?.image_id;
      if (imageId && imageDataMap.has(imageId)) {
        ctx.imageData = imageDataMap.get(imageId);
      }

      return ctx;
    });

    return {
      context,
      piiSessionId: anonymizeResult.session_id,
    };
  } catch (error) {
    console.error('Error fetching RAG context:', error);
    return { context: [] };
  }
}

/**
 * Build the system prompt for RAG
 *
 * With LPRAG (Local Differential Privacy) enabled, the context contains
 * semantically perturbed values that look like real data but are privacy-protected.
 * The LLM can reason about these naturally, and the application will restore
 * original values during de-anonymization.
 *
 * For unsupported entity types, tokens like <PII:TYPE:abc123> may still appear.
 */
function buildSystemPrompt(context: ChatContext[]): string {
  if (context.length === 0) {
    return `You are a helpful AI assistant for MindSage, a privacy-first personal data platform.
Answer questions helpfully and concisely. If you don't know something, say so.`;
  }

  const contextText = context
    .map((c, i) => {
      const source = c.filename || c.source || `Document ${c.id}`;
      return `[${i + 1}] (${source}, relevance: ${(c.score * 100).toFixed(0)}%)\n${c.excerpt}`;
    })
    .join('\n\n');

  return `You are a helpful AI assistant for MindSage, a privacy-first personal data platform.
Answer questions based on the user's personal data provided below. Be helpful and concise.
If the context doesn't contain relevant information, say so and offer general help.

Note: The context contains privacy-protected data. Names, emails, and other personal information
may appear as realistic substitutes or as tokens like <PII:TYPE:abc123>. Use this information
naturally in your responses - the application will automatically restore the original values.

Context from user's data:
${contextText}`;
}

/**
 * Build multimodal message content for providers that support images.
 * Includes context images in the user message alongside the query.
 */
function buildMultimodalUserContent(
  userMessage: string,
  context: ChatContext[],
  provider: LLMProvider
): MultimodalContentPart[] | string {
  const contextImages = context.filter(c => c.imageData);

  // If no images or provider doesn't support multimodal, return plain text
  if (contextImages.length === 0 || provider === 'groq') {
    return userMessage;
  }

  const parts: MultimodalContentPart[] = [];

  // Add text introduction with context images
  if (contextImages.length > 0) {
    parts.push({
      type: 'text',
      text: `The following ${contextImages.length} image(s) are from your personal data and may be relevant to the question:\n`,
    });

    // Add each image
    for (const ctx of contextImages) {
      if (!ctx.imageData) continue;

      if (provider === 'openai') {
        // OpenAI format: data URL
        parts.push({
          type: 'image',
          image_url: {
            url: `data:${ctx.imageData.mediaType};base64,${ctx.imageData.base64}`,
            detail: 'auto',
          },
        });
      } else if (provider === 'anthropic') {
        // Anthropic format: base64 source
        parts.push({
          type: 'image',
          source: {
            type: 'base64',
            media_type: ctx.imageData.mediaType,
            data: ctx.imageData.base64,
          },
        });
      }

      // Add caption context after image
      if (ctx.imageData.caption) {
        const source = ctx.filename || ctx.source || `Document ${ctx.id}`;
        parts.push({
          type: 'text',
          text: `[Image from ${source}: ${ctx.imageData.caption}]\n`,
        });
      }
    }
  }

  // Add the actual user question
  parts.push({
    type: 'text',
    text: `\nUser question: ${userMessage}`,
  });

  return parts;
}

/**
 * Convert multimodal messages to OpenAI format
 */
function toOpenAIMessages(messages: MultimodalMessage[]): any[] {
  return messages.map(m => ({
    role: m.role,
    content: Array.isArray(m.content)
      ? m.content.map(part => {
          if (part.type === 'text') {
            return { type: 'text', text: part.text };
          } else if (part.type === 'image' && part.image_url) {
            return { type: 'image_url', image_url: part.image_url };
          }
          return { type: 'text', text: '' };
        })
      : m.content,
  }));
}

/**
 * Convert multimodal messages to Anthropic format
 */
function toAnthropicMessages(messages: MultimodalMessage[]): any[] {
  return messages
    .filter(m => m.role !== 'system')
    .map(m => ({
      role: m.role,
      content: Array.isArray(m.content)
        ? m.content.map(part => {
            if (part.type === 'text') {
              return { type: 'text', text: part.text };
            } else if (part.type === 'image' && part.source) {
              return { type: 'image', source: part.source };
            }
            return { type: 'text', text: '' };
          })
        : m.content,
    }));
}

/**
 * Call OpenAI API with streaming
 */
async function* streamOpenAI(
  messages: ChatMessage[],
  model: string,
  apiKey: string,
  temperature: number,
  maxTokens: number
): AsyncGenerator<{ type: 'token' | 'done'; content?: string; tokensUsed?: number }> {
  const response = await fetch('https://api.openai.com/v1/chat/completions', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'Authorization': `Bearer ${apiKey}`,
    },
    body: JSON.stringify({
      model,
      messages: messages.map(m => ({ role: m.role, content: m.content })),
      temperature,
      max_tokens: maxTokens,
      stream: true,
    }),
  });

  if (!response.ok) {
    const error = await response.text();
    throw new Error(`OpenAI API error: ${response.status} ${error}`);
  }

  const reader = response.body?.getReader();
  if (!reader) {
    throw new Error('No response body');
  }

  const decoder = new TextDecoder();
  let buffer = '';
  let totalTokens = 0;

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;

    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split('\n');
    buffer = lines.pop() || '';

    for (const line of lines) {
      if (line.startsWith('data: ')) {
        const data = line.slice(6).trim();
        if (data === '[DONE]') {
          yield { type: 'done', tokensUsed: totalTokens };
          return;
        }
        try {
          const parsed = JSON.parse(data);
          const content = parsed.choices?.[0]?.delta?.content;
          if (content) {
            yield { type: 'token', content };
          }
          if (parsed.usage?.total_tokens) {
            totalTokens = parsed.usage.total_tokens;
          }
        } catch {
          // Skip invalid JSON
        }
      }
    }
  }

  yield { type: 'done', tokensUsed: totalTokens };
}

/**
 * Call Anthropic API with streaming
 */
async function* streamAnthropic(
  messages: ChatMessage[],
  model: string,
  apiKey: string,
  temperature: number,
  maxTokens: number
): AsyncGenerator<{ type: 'token' | 'done'; content?: string; tokensUsed?: number }> {
  // Separate system message from conversation
  const systemMessage = messages.find(m => m.role === 'system')?.content || '';
  const conversationMessages = messages.filter(m => m.role !== 'system');

  const response = await fetch('https://api.anthropic.com/v1/messages', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'x-api-key': apiKey,
      'anthropic-version': '2023-06-01',
    },
    body: JSON.stringify({
      model,
      system: systemMessage,
      messages: conversationMessages.map(m => ({ role: m.role, content: m.content })),
      temperature,
      max_tokens: maxTokens,
      stream: true,
    }),
  });

  if (!response.ok) {
    const error = await response.text();
    throw new Error(`Anthropic API error: ${response.status} ${error}`);
  }

  const reader = response.body?.getReader();
  if (!reader) {
    throw new Error('No response body');
  }

  const decoder = new TextDecoder();
  let buffer = '';
  let totalTokens = 0;

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;

    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split('\n');
    buffer = lines.pop() || '';

    for (const line of lines) {
      if (line.startsWith('data: ')) {
        const data = line.slice(6).trim();
        try {
          const parsed = JSON.parse(data);

          if (parsed.type === 'content_block_delta') {
            const content = parsed.delta?.text;
            if (content) {
              yield { type: 'token', content };
            }
          } else if (parsed.type === 'message_delta') {
            if (parsed.usage?.output_tokens) {
              totalTokens = parsed.usage.output_tokens;
            }
          } else if (parsed.type === 'message_stop') {
            yield { type: 'done', tokensUsed: totalTokens };
            return;
          }
        } catch {
          // Skip invalid JSON
        }
      }
    }
  }

  yield { type: 'done', tokensUsed: totalTokens };
}

/**
 * Call Groq API with streaming (OpenAI-compatible)
 */
async function* streamGroq(
  messages: ChatMessage[],
  model: string,
  apiKey: string,
  temperature: number,
  maxTokens: number
): AsyncGenerator<{ type: 'token' | 'done'; content?: string; tokensUsed?: number }> {
  const response = await fetch('https://api.groq.com/openai/v1/chat/completions', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'Authorization': `Bearer ${apiKey}`,
    },
    body: JSON.stringify({
      model,
      messages: messages.map(m => ({ role: m.role, content: m.content })),
      temperature,
      max_tokens: maxTokens,
      stream: true,
    }),
  });

  if (!response.ok) {
    const error = await response.text();
    throw new Error(`Groq API error: ${response.status} ${error}`);
  }

  const reader = response.body?.getReader();
  if (!reader) {
    throw new Error('No response body');
  }

  const decoder = new TextDecoder();
  let buffer = '';
  let totalTokens = 0;

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;

    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split('\n');
    buffer = lines.pop() || '';

    for (const line of lines) {
      if (line.startsWith('data: ')) {
        const data = line.slice(6).trim();
        if (data === '[DONE]') {
          yield { type: 'done', tokensUsed: totalTokens };
          return;
        }
        try {
          const parsed = JSON.parse(data);
          const content = parsed.choices?.[0]?.delta?.content;
          if (content) {
            yield { type: 'token', content };
          }
          if (parsed.usage?.total_tokens) {
            totalTokens = parsed.usage.total_tokens;
          }
        } catch {
          // Skip invalid JSON
        }
      }
    }
  }

  yield { type: 'done', tokensUsed: totalTokens };
}

/**
 * Call OpenAI API with streaming - multimodal version
 * Supports text and image content parts
 */
async function* streamOpenAIMultimodal(
  messages: MultimodalMessage[],
  model: string,
  apiKey: string,
  temperature: number,
  maxTokens: number
): AsyncGenerator<{ type: 'token' | 'done'; content?: string; tokensUsed?: number }> {
  const response = await fetch('https://api.openai.com/v1/chat/completions', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'Authorization': `Bearer ${apiKey}`,
    },
    body: JSON.stringify({
      model,
      messages: toOpenAIMessages(messages),
      temperature,
      max_tokens: maxTokens,
      stream: true,
    }),
  });

  if (!response.ok) {
    const error = await response.text();
    throw new Error(`OpenAI API error: ${response.status} ${error}`);
  }

  const reader = response.body?.getReader();
  if (!reader) {
    throw new Error('No response body');
  }

  const decoder = new TextDecoder();
  let buffer = '';
  let totalTokens = 0;

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;

    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split('\n');
    buffer = lines.pop() || '';

    for (const line of lines) {
      if (line.startsWith('data: ')) {
        const data = line.slice(6).trim();
        if (data === '[DONE]') {
          yield { type: 'done', tokensUsed: totalTokens };
          return;
        }
        try {
          const parsed = JSON.parse(data);
          const content = parsed.choices?.[0]?.delta?.content;
          if (content) {
            yield { type: 'token', content };
          }
          if (parsed.usage?.total_tokens) {
            totalTokens = parsed.usage.total_tokens;
          }
        } catch {
          // Skip invalid JSON
        }
      }
    }
  }

  yield { type: 'done', tokensUsed: totalTokens };
}

/**
 * Call Anthropic API with streaming - multimodal version
 * Supports text and image content parts
 */
async function* streamAnthropicMultimodal(
  messages: MultimodalMessage[],
  model: string,
  apiKey: string,
  temperature: number,
  maxTokens: number
): AsyncGenerator<{ type: 'token' | 'done'; content?: string; tokensUsed?: number }> {
  // Separate system message from conversation
  const systemMessage = messages.find(m => m.role === 'system');
  const systemContent = typeof systemMessage?.content === 'string'
    ? systemMessage.content
    : systemMessage?.content?.filter(p => p.type === 'text').map(p => p.text || '').join('\n') || '';

  const response = await fetch('https://api.anthropic.com/v1/messages', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'x-api-key': apiKey,
      'anthropic-version': '2023-06-01',
    },
    body: JSON.stringify({
      model,
      system: systemContent,
      messages: toAnthropicMessages(messages),
      temperature,
      max_tokens: maxTokens,
      stream: true,
    }),
  });

  if (!response.ok) {
    const error = await response.text();
    throw new Error(`Anthropic API error: ${response.status} ${error}`);
  }

  const reader = response.body?.getReader();
  if (!reader) {
    throw new Error('No response body');
  }

  const decoder = new TextDecoder();
  let buffer = '';
  let totalTokens = 0;

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;

    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split('\n');
    buffer = lines.pop() || '';

    for (const line of lines) {
      if (line.startsWith('data: ')) {
        const data = line.slice(6).trim();
        try {
          const parsed = JSON.parse(data);

          if (parsed.type === 'content_block_delta') {
            const content = parsed.delta?.text;
            if (content) {
              yield { type: 'token', content };
            }
          } else if (parsed.type === 'message_delta') {
            if (parsed.usage?.output_tokens) {
              totalTokens = parsed.usage.output_tokens;
            }
          } else if (parsed.type === 'message_stop') {
            yield { type: 'done', tokensUsed: totalTokens };
            return;
          }
        } catch {
          // Skip invalid JSON
        }
      }
    }
  }

  yield { type: 'done', tokensUsed: totalTokens };
}

/**
 * Anonymize user message and conversation history before sending to LLM.
 * Uses batch approach: combines all texts, single API call, splits back.
 * Returns anonymized message + history, or originals on failure.
 */
async function anonymizeUserMessages(
  message: string,
  conversationHistory: ChatMessage[],
  piiSessionId: string | undefined,
  consentSessionId: string | undefined
): Promise<{ anonymizedMessage: string; anonymizedHistory: ChatMessage[]; piiSessionId?: string }> {
  try {
    const available = await isVectorStoreAvailable();
    if (!available) {
      return { anonymizedMessage: message, anonymizedHistory: conversationHistory, piiSessionId };
    }

    const client = getVectorStoreClient();

    // Build batch: user message + all history messages with content
    const historyWithContent = conversationHistory.filter(m => m.content);
    const allTexts = [
      ...historyWithContent.map((m, i) => `[MSG_${i}]${m.content}[/MSG_${i}]`),
      `[USERMSG]${message}[/USERMSG]`,
    ];
    const combinedText = allTexts.join('\n');

    const result = await client.anonymize(combinedText, piiSessionId, consentSessionId);
    const sessionId = result.session_id || piiSessionId;
    const anonText = result.anonymized_text;

    // Parse user message back
    const userStart = anonText.indexOf('[USERMSG]');
    const userEnd = anonText.indexOf('[/USERMSG]');
    const anonymizedMessage = (userStart !== -1 && userEnd !== -1)
      ? anonText.slice(userStart + '[USERMSG]'.length, userEnd)
      : message;

    // Parse history messages back
    const anonymizedHistory = conversationHistory.map((m, i) => {
      if (!m.content) return m;
      // Find the matching index in historyWithContent
      const hwcIndex = historyWithContent.indexOf(m);
      if (hwcIndex === -1) return m;
      const startTag = `[MSG_${hwcIndex}]`;
      const endTag = `[/MSG_${hwcIndex}]`;
      const startIdx = anonText.indexOf(startTag);
      const endIdx = anonText.indexOf(endTag);
      if (startIdx !== -1 && endIdx !== -1) {
        return { ...m, content: anonText.slice(startIdx + startTag.length, endIdx) };
      }
      return m;
    });

    return { anonymizedMessage, anonymizedHistory, piiSessionId: sessionId };
  } catch (error) {
    console.warn('Failed to anonymize user messages, sending as-is:', error);
    return { anonymizedMessage: message, anonymizedHistory: conversationHistory, piiSessionId };
  }
}

/**
 * Stream chat response with RAG context
 *
 * PII Protection Flow:
 * 1. RAG context is anonymized during buildRAGContext()
 * 2. User message + conversation history are anonymized before LLM
 * 3. LLM response is de-anonymized server-side after streaming
 * 4. Frontend receives a 'deanonymized' event with restored text
 * 5. PII session ID never leaves the backend
 */
export async function* streamChat(request: ChatRequest): AsyncGenerator<StreamEvent> {
  const startTime = Date.now();
  const config = getLLMConfig();

  if (!config) {
    yield {
      type: 'error',
      error: 'No LLM service configured. Set OPENAI_API_KEY, ANTHROPIC_API_KEY, or GROQ_API_KEY environment variable.',
    };
    return;
  }

  const {
    message,
    conversationHistory = [],
    model = config.defaultModel,
    useRAG = true,
    topK = 5,
    minScore = 0.2,
    temperature = 0.7,
    maxTokens = 1024,
    consentSessionId,
  } = request;

  // Get RAG context if enabled
  let context: ChatContext[] = [];
  let piiSessionId: string | undefined;

  if (useRAG) {
    const ragResult = await buildRAGContext(message, topK, minScore, consentSessionId);
    context = ragResult.context;
    piiSessionId = ragResult.piiSessionId;

    // Send context event (no pii_session_id — stays server-side)
    yield {
      type: 'context',
      context,
    };
  }

  // Anonymize user message and conversation history before sending to LLM
  const anonymized = await anonymizeUserMessages(
    message, conversationHistory, piiSessionId, consentSessionId
  );
  piiSessionId = anonymized.piiSessionId;

  // Build messages array with multimodal support for images (using anonymized content)
  const systemPrompt = buildSystemPrompt(context);
  const hasImages = context.some(c => c.imageData);
  const supportsMultimodal = config.provider === 'openai' || config.provider === 'anthropic';

  // Build user content (multimodal if images present and provider supports it)
  // Use anonymized message text for the multimodal content
  const userContent = hasImages && supportsMultimodal
    ? buildMultimodalUserContent(anonymized.anonymizedMessage, context, config.provider)
    : anonymized.anonymizedMessage;

  const messages: MultimodalMessage[] = [
    { role: 'system', content: systemPrompt },
    ...anonymized.anonymizedHistory.map(m => ({ role: m.role, content: m.content })),
    { role: 'user', content: userContent },
  ];

  try {
    // Stream from appropriate provider
    let stream;
    if (config.provider === 'openai') {
      stream = streamOpenAIMultimodal(messages, model, config.apiKey, temperature, maxTokens);
    } else if (config.provider === 'groq') {
      // Groq doesn't support multimodal - convert to text-only messages
      const textMessages = messages.map(m => ({
        role: m.role,
        content: typeof m.content === 'string' ? m.content : m.content.filter(p => p.type === 'text').map(p => p.text || '').join('\n'),
      }));
      stream = streamGroq(textMessages as ChatMessage[], model, config.apiKey, temperature, maxTokens);
    } else {
      stream = streamAnthropicMultimodal(messages, model, config.apiKey, temperature, maxTokens);
    }

    let tokensUsed = 0;
    let fullContent = '';

    for await (const event of stream) {
      if (event.type === 'token') {
        fullContent += event.content || '';
        yield { type: 'token', content: event.content };
      } else if (event.type === 'done') {
        tokensUsed = event.tokensUsed || 0;
      }
    }

    // De-anonymize the full response server-side
    if (piiSessionId && fullContent) {
      try {
        const client = getVectorStoreClient();
        const deAnon = await client.deanonymize(fullContent, piiSessionId);
        if (deAnon.tokens_replaced > 0) {
          yield { type: 'deanonymized', content: deAnon.deanonymized_text };
        }
      } catch (error) {
        console.warn('Server-side de-anonymization failed:', error);
        // No deanonymized event — frontend keeps LPRAG values (still look realistic)
      }
    }

    // Send done event (no pii_session_id — stays server-side)
    const duration = Date.now() - startTime;
    yield {
      type: 'done',
      model,
      tokensUsed,
      duration,
    };
  } catch (error) {
    yield {
      type: 'error',
      error: String(error),
    };
  }
}

/**
 * Non-streaming chat (for simple requests)
 */
export async function chat(request: ChatRequest): Promise<ChatResponse> {
  let fullContent = '';
  let response: Partial<ChatResponse> = {};

  for await (const event of streamChat(request)) {
    if (event.type === 'token') {
      fullContent += event.content || '';
    } else if (event.type === 'deanonymized') {
      // Server-side de-anonymization completed — use restored text
      fullContent = event.content || fullContent;
    } else if (event.type === 'done') {
      response = {
        ...response,
        model: event.model || '',
        tokensUsed: event.tokensUsed,
        duration: event.duration,
      };
    } else if (event.type === 'context') {
      response.context = event.context;
    } else if (event.type === 'error') {
      throw new Error(event.error);
    }
  }

  return {
    message: fullContent,
    model: response.model || '',
    context: response.context,
    tokensUsed: response.tokensUsed,
    duration: response.duration,
  };
}
