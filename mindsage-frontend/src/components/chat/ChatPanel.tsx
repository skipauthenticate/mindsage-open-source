import { useState, useRef, useEffect, useCallback } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { Send, User, Loader2, AlertCircle, Sparkles, Mic, PhoneOff, RotateCcw, X, Square } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Textarea } from '@/components/ui/textarea';
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from '@/components/ui/alert-dialog';
import { ScrollArea } from '@/components/ui/scroll-area';
import { LLMConfigDialog } from './LLMConfigDialog';
import { SourcesList } from './SourcesList';
import { ConsentDialog, useConsent } from '@/components/consent';
import { useBackendChat, Message } from '@/hooks/use-backend-chat';
import { useVoiceRTC } from '@/hooks/use-voice-rtc';
import ReactMarkdown from 'react-markdown';

export function ChatPanel() {
  const [input, setInput] = useState('');
  const [consentSessionId, setConsentSessionId] = useState<string | null>(null);

  const {
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
  } = useBackendChat({ consentSessionId });

  // WebRTC voice hook
  const voiceRTC = useVoiceRTC({
    onTranscript: (text) => {
      // Add user's transcribed speech as a message
      addVoiceMessages(text, null);
    },
    onResponse: (text) => {
      // Add assistant's voice response as a message
      addVoiceMessages(null, text);
    },
    onSources: (_sources) => {
      // Sources are displayed inline — could be enhanced later
    },
    onError: (message) => {
      console.error('Voice error:', message);
    },
  });

  // Consent hook for auto-creating session
  const {
    isAvailable: isConsentAvailable,
    isLoading: isConsentLoading,
    createSession,
  } = useConsent(consentSessionId);

  const scrollRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  // Auto-create consent session with "balanced" preset when LLM is configured
  useEffect(() => {
    if (isConfigured && !consentSessionId && isConsentAvailable && !isConsentLoading && !createSession.isPending) {
      createSession.mutate('balanced', {
        onSuccess: (data) => {
          setConsentSessionId(data.session_id);
        },
      });
    }
  }, [isConfigured, consentSessionId, isConsentAvailable, isConsentLoading, createSession]);

  useEffect(() => {
    if (scrollRef.current) {
      // ScrollArea's actual scrollable element is the Viewport child
      const viewport = scrollRef.current.querySelector('[data-radix-scroll-area-viewport]');
      const target = viewport || scrollRef.current;
      target.scrollTop = target.scrollHeight;
    }
  }, [messages]);

  const handleSubmit = async () => {
    if (!input.trim() || isLoading) return;
    if (!isConfigured) {
      return;
    }

    const message = input.trim();
    setInput('');
    // Reset textarea height after clearing
    if (textareaRef.current) {
      textareaRef.current.style.height = 'auto';
    }
    await sendMessage(message);
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSubmit();
    }
  };

  const handleMicClick = () => {
    voiceRTC.toggleConnection();
  };

  const providerLabel = provider
    ? `${provider}${model ? ` - ${model}` : ''}`
    : 'No provider configured';

  const micAvailable = voiceRTC.isAvailable;
  const isVoiceConnected = voiceRTC.state === 'connected';
  const isVoiceConnecting = voiceRTC.state === 'connecting';

  return (
    <div className="h-full flex flex-col bg-background">
      {/* Messages Area */}
      <ScrollArea className="flex-1" ref={scrollRef}>
        <div className="max-w-3xl mx-auto px-4 py-6">
          <AnimatePresence mode="popLayout">
            {messages.length === 0 ? (
              <motion.div
                initial={{ opacity: 0, y: 20 }}
                animate={{ opacity: 1, y: 0 }}
                className="flex flex-col items-center justify-center py-20 text-center"
              >
                <div className="h-12 w-12 rounded-full bg-primary/10 flex items-center justify-center mb-4">
                  <Sparkles className="h-6 w-6 text-primary" />
                </div>
                <h3 className="text-lg font-medium text-foreground mb-2">
                  {isConfigured ? 'How can I help you today?' : 'Get Started'}
                </h3>
                <p className="text-sm text-muted-foreground max-w-sm">
                  {isConfigured
                    ? 'Ask me anything about your knowledge base. I can search your documents and provide context-aware answers.'
                    : 'Configure an LLM provider to start chatting'}
                </p>
                {!isConfigured && (
                  <div className="mt-4">
                    <LLMConfigDialog />
                  </div>
                )}
              </motion.div>
            ) : (
              <div className="space-y-6">
                {messages.map((message, index) => {
                  const isLastMessage = index === messages.length - 1;
                  const isAssistantLoading = message.role === 'assistant' && isLastMessage && isLoading && !message.content;

                  return (
                  <motion.div
                    key={message.id}
                    initial={{ opacity: 0, y: 10 }}
                    animate={{ opacity: 1, y: 0 }}
                    className="group"
                  >
                    <div className={`flex gap-4 ${message.role === 'user' ? 'flex-row-reverse' : ''}`}>
                      <div className={`h-8 w-8 rounded-full flex items-center justify-center shrink-0 ${
                        message.role === 'assistant'
                          ? 'bg-primary text-primary-foreground'
                          : 'bg-muted'
                      }`}>
                        {message.role === 'assistant' ? (
                          isAssistantLoading ? (
                            <Loader2 className="h-4 w-4 animate-spin" />
                          ) : (
                            <Sparkles className="h-4 w-4" />
                          )
                        ) : (
                          message.voiceInitiated ? (
                            <Mic className="h-4 w-4" />
                          ) : (
                            <User className="h-4 w-4" />
                          )
                        )}
                      </div>
                      <div className={`flex-1 ${message.role === 'user' ? 'text-right' : ''}`}>
                        <div
                          className={`inline-block rounded-2xl px-4 py-3 max-w-[90%] ${
                            message.role === 'user'
                              ? 'bg-primary text-primary-foreground rounded-br-md'
                              : 'bg-muted rounded-bl-md'
                          }`}
                        >
                          {message.role === 'assistant' ? (
                            <div className="prose prose-sm dark:prose-invert max-w-none">
                              <ReactMarkdown>{message.content || '...'}</ReactMarkdown>
                            </div>
                          ) : (
                            <p className="text-sm whitespace-pre-wrap">{message.content}</p>
                          )}
                        </div>
                        {message.role === 'assistant' && message.context && message.context.length > 0 && (
                          <SourcesList sources={message.context} className="mt-2" />
                        )}
                      </div>
                    </div>
                  </motion.div>
                  );
                })}
              </div>
            )}
          </AnimatePresence>
        </div>
      </ScrollArea>

      {/* Error */}
      {error && (
        <motion.div
          initial={{ opacity: 0, y: 10 }}
          animate={{ opacity: 1, y: 0 }}
          className="max-w-3xl mx-auto w-full px-4"
        >
          <div className="flex items-center gap-2 p-3 rounded-lg bg-destructive/10 text-destructive text-sm mb-2">
            <AlertCircle className="h-4 w-4 shrink-0" />
            <span className="flex-1">{error}</span>
            <Button
              variant="ghost"
              size="icon"
              className="h-5 w-5 shrink-0 text-destructive hover:text-destructive"
              onClick={dismissError}
            >
              <X className="h-3 w-3" />
            </Button>
          </div>
        </motion.div>
      )}

      {/* Input Area */}
      <div className="border-t border-border bg-background/80 backdrop-blur-sm">
        <div className="max-w-3xl mx-auto px-4 py-4">
          <div className="relative flex items-end gap-2">
            {/* Voice WebRTC button */}
            {isConfigured && micAvailable && (
              <div className="flex flex-col items-center gap-0.5 shrink-0">
                <Button
                  variant={isVoiceConnected ? 'destructive' : 'secondary'}
                  size="icon"
                  className={`h-10 w-10 rounded-full ${
                    isVoiceConnected
                      ? 'animate-pulse ring-2 ring-destructive'
                      : ''
                  }`}
                  onClick={handleMicClick}
                  disabled={isVoiceConnecting}
                  aria-label={
                    isVoiceConnected
                      ? 'Disconnect voice'
                      : isVoiceConnecting
                      ? 'Connecting'
                      : 'Start voice chat'
                  }
                  title={
                    isVoiceConnected
                      ? 'Disconnect voice (click to stop)'
                      : isVoiceConnecting
                      ? 'Connecting...'
                      : 'Start voice chat (WebRTC)'
                  }
                >
                  {isVoiceConnecting && <Loader2 className="h-4 w-4 animate-spin" />}
                  {isVoiceConnected && <PhoneOff className="h-4 w-4" />}
                  {!isVoiceConnected && !isVoiceConnecting && <Mic className="h-4 w-4" />}
                </Button>
                {(isVoiceConnected || isVoiceConnecting) && (
                  <span className={`text-[9px] font-medium ${isVoiceConnected ? 'text-destructive' : 'text-muted-foreground'}`}>
                    {isVoiceConnecting ? 'Connecting' : 'Listening'}
                  </span>
                )}
              </div>
            )}
            <div className="flex-1 relative">
              <Textarea
                ref={textareaRef}
                placeholder={
                  isVoiceConnected
                    ? "Voice active — speak naturally..."
                    : isConfigured
                    ? "Message..."
                    : "Configure a provider to start..."
                }
                value={input}
                onChange={(e) => {
                  setInput(e.target.value);
                  // Auto-resize textarea
                  const el = e.target;
                  el.style.height = 'auto';
                  el.style.height = `${Math.min(el.scrollHeight, 200)}px`;
                }}
                onKeyDown={handleKeyDown}
                disabled={!isConfigured || isLoading}
                className="min-h-[44px] max-h-[200px] resize-none rounded-2xl pr-12 py-3.5 bg-muted border-0 focus-visible:ring-1 focus-visible:ring-ring"
                rows={1}
              />
              {isLoading ? (
                <Button
                  onClick={stopGeneration}
                  size="icon"
                  variant="destructive"
                  className="absolute right-2 bottom-2 h-8 w-8 rounded-full"
                  title="Stop generating"
                  aria-label="Stop generating"
                >
                  <Square className="h-3.5 w-3.5" />
                </Button>
              ) : (
                <Button
                  onClick={handleSubmit}
                  disabled={!input.trim() || !isConfigured}
                  size="icon"
                  className="absolute right-2 bottom-2 h-8 w-8 rounded-full"
                  aria-label="Send message"
                >
                  <Send className="h-4 w-4" />
                </Button>
              )}
            </div>
            {isConfigured && (
              <>
                <ConsentDialog
                  sessionId={consentSessionId}
                  onSessionCreated={setConsentSessionId}
                />
                <LLMConfigDialog />
              </>
            )}
          </div>
          <div className="flex items-center justify-center gap-2 mt-3">
            <p className="text-xs text-muted-foreground">
              {isVoiceConnected
                ? 'Voice active — speak naturally, responses play automatically'
                : providerLabel}
            </p>
            {messages.length > 0 && (
              <AlertDialog>
                <AlertDialogTrigger asChild>
                  <Button
                    variant="ghost"
                    size="sm"
                    className="h-5 px-1.5 text-[10px] text-muted-foreground hover:text-foreground gap-1"
                    title="Start new conversation"
                  >
                    <RotateCcw className="h-3 w-3" />
                    New chat
                  </Button>
                </AlertDialogTrigger>
                <AlertDialogContent>
                  <AlertDialogHeader>
                    <AlertDialogTitle>Start new conversation?</AlertDialogTitle>
                    <AlertDialogDescription>
                      This will clear the current conversation ({messages.length} message{messages.length !== 1 ? 's' : ''}). This cannot be undone.
                    </AlertDialogDescription>
                  </AlertDialogHeader>
                  <AlertDialogFooter>
                    <AlertDialogCancel>Cancel</AlertDialogCancel>
                    <AlertDialogAction onClick={clearMessages}>
                      Clear & start new
                    </AlertDialogAction>
                  </AlertDialogFooter>
                </AlertDialogContent>
              </AlertDialog>
            )}
          </div>
          <p className="text-[10px] text-muted-foreground/70 text-center mt-1">
            Enter to send · Shift+Enter for newline
          </p>
        </div>
      </div>
    </div>
  );
}
