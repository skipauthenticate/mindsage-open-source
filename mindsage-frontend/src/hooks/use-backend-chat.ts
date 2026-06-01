import { useState, useCallback, useRef } from 'react';
import { useQuery } from '@tanstack/react-query';
import { api, type ChatContext, StreamEvent } from '@/lib/api';

export interface Message {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  timestamp: Date;
  context?: ChatContext[];
  voiceInitiated?: boolean;
}

interface UseBackendChatOptions {
  consentSessionId?: string | null;
}

interface UseBackendChatReturn {
  isAvailable: boolean;
  isLoading: boolean;
  isConfigured: boolean;
  error: string | null;
  provider: string | null;
  model: string | null;
  messages: Message[];
  sendMessage: (content: string, voiceInitiated?: boolean) => Promise<void>;
  addVoiceMessages: (transcript: string | null, response: string | null) => void;
  clearMessages: () => void;
  stopGeneration: () => void;
  dismissError: () => void;
}

export function useBackendChat(options: UseBackendChatOptions = {}): UseBackendChatReturn {
  const { consentSessionId } = options;
  const [messages, setMessages] = useState<Message[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const abortControllerRef = useRef<AbortController | null>(null);

  // Query chat status to check if backend is configured
  const { data: chatStatus } = useQuery({
    queryKey: ['chatStatus'],
    queryFn: api.getChatStatus,
    refetchInterval: 30000, // Refetch every 30s
    staleTime: 10000,
  });

  const isAvailable = chatStatus?.llmAvailable ?? false;
  const isConfigured = !!chatStatus?.llmProvider;
  const provider = chatStatus?.llmProvider ?? null;
  const model = chatStatus?.defaultModel ?? null;

  const sendMessage = useCallback(async (content: string, voiceInitiated?: boolean) => {
    if (!content.trim() || isLoading) return;

    // Create user message
    const userMessage: Message = {
      id: crypto.randomUUID(),
      role: 'user',
      content: content.trim(),
      timestamp: new Date(),
      voiceInitiated,
    };

    setMessages(prev => [...prev, userMessage]);
    setError(null);
    setIsLoading(true);

    // Create placeholder assistant message
    const assistantMessage: Message = {
      id: crypto.randomUUID(),
      role: 'assistant',
      content: '',
      timestamp: new Date(),
      voiceInitiated,
    };

    setMessages(prev => [...prev, assistantMessage]);

    try {
      // Build conversation history for the API
      const conversationHistory = messages.map(m => ({
        role: m.role as 'user' | 'assistant',
        content: m.content,
      }));

      let context: ChatContext[] | undefined;
      let fullContent = '';

      // Create abort controller for this request
      const abortController = new AbortController();
      abortControllerRef.current = abortController;

      // Stream the response
      for await (const event of api.streamChatMessage({
        message: content,
        conversationHistory,
        useRAG: true,
        topK: 5,
        minScore: 0.2,
        consentSessionId: consentSessionId || undefined,
        voiceInitiated,
      }, abortController.signal)) {
        if (event.type === 'context') {
          context = event.context;
          setMessages(prev => {
            const updated = [...prev];
            const lastMessage = updated[updated.length - 1];
            if (lastMessage.role === 'assistant') {
              lastMessage.context = context;
            }
            return updated;
          });
        } else if (event.type === 'token') {
          fullContent += event.content || '';
          setMessages(prev => {
            const updated = [...prev];
            const lastMessage = updated[updated.length - 1];
            if (lastMessage.role === 'assistant') {
              lastMessage.content = fullContent;
            }
            return updated;
          });
        } else if (event.type === 'deanonymized') {
          // Server-side de-anonymization completed — swap in restored text
          fullContent = event.content || fullContent;
          setMessages(prev => {
            const updated = [...prev];
            const lastMessage = updated[updated.length - 1];
            if (lastMessage.role === 'assistant') {
              lastMessage.content = fullContent;
            }
            return updated;
          });
        } else if (event.type === 'done') {
          // Streaming complete
        } else if (event.type === 'error') {
          throw new Error(event.error || 'Stream error');
        }
      }
    } catch (err) {
      if (err instanceof DOMException && err.name === 'AbortError') {
        // User cancelled — keep partial content if any
        setMessages(prev => {
          const updated = [...prev];
          const lastMsg = updated[updated.length - 1];
          if (lastMsg?.role === 'assistant' && !lastMsg.content) {
            return prev.slice(0, -1); // Remove empty placeholder
          }
          return updated; // Keep partial response
        });
      } else {
        const errorMessage = err instanceof Error ? err.message : 'Failed to get response';
        setError(errorMessage);
        // Remove the empty assistant message on error
        setMessages(prev => prev.slice(0, -1));
      }
    } finally {
      abortControllerRef.current = null;
      setIsLoading(false);
    }
  }, [messages, isLoading, consentSessionId]);

  const addVoiceMessages = useCallback((transcript: string | null, response: string | null) => {
    if (transcript) {
      setMessages(prev => [...prev, {
        id: crypto.randomUUID(),
        role: 'user',
        content: transcript,
        timestamp: new Date(),
        voiceInitiated: true,
      }]);
    }
    if (response) {
      setMessages(prev => [...prev, {
        id: crypto.randomUUID(),
        role: 'assistant',
        content: response,
        timestamp: new Date(),
        voiceInitiated: true,
      }]);
    }
  }, []);

  const dismissError = useCallback(() => {
    setError(null);
  }, []);

  const stopGeneration = useCallback(() => {
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
    }
  }, []);

  const clearMessages = useCallback(() => {
    // Abort any ongoing request
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
    }
    setMessages([]);
    setError(null);
  }, []);

  return {
    isAvailable,
    isLoading,
    isConfigured,
    error,
    provider,
    model,
    messages,
    sendMessage,
    addVoiceMessages,
    clearMessages,
    stopGeneration,
    dismissError,
  };
}
