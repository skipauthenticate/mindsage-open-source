import { useState, useCallback, useRef, useEffect } from 'react';
import { api } from '@/lib/api';

export type VoiceRTCState = 'disconnected' | 'connecting' | 'connected' | 'error';

export interface VoiceTextEvent {
  type: 'transcript' | 'response' | 'sources' | 'error';
  data: Record<string, unknown>;
}

interface UseVoiceRTCOptions {
  /** Called when user's speech is transcribed */
  onTranscript?: (text: string) => void;
  /** Called when assistant response text is received */
  onResponse?: (text: string) => void;
  /** Called when search sources are received */
  onSources?: (sources: Array<{ id: number; excerpt: string; score: number }>) => void;
  /** Called on error */
  onError?: (message: string) => void;
}

interface UseVoiceRTCReturn {
  state: VoiceRTCState;
  isAvailable: boolean;
  connect: () => Promise<void>;
  disconnect: () => void;
  toggleConnection: () => void;
}

export function useVoiceRTC(options: UseVoiceRTCOptions = {}): UseVoiceRTCReturn {
  const [state, setState] = useState<VoiceRTCState>('disconnected');
  const pcRef = useRef<RTCPeerConnection | null>(null);
  const localStreamRef = useRef<MediaStream | null>(null);
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const eventSourceRef = useRef<EventSource | null>(null);
  const webrtcIdRef = useRef<string>('');
  const errorTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const optionsRef = useRef(options);
  optionsRef.current = options;

  // Check browser support
  const isAvailable =
    typeof navigator !== 'undefined' &&
    !!navigator.mediaDevices?.getUserMedia &&
    typeof RTCPeerConnection !== 'undefined';

  const cleanup = useCallback(() => {
    // Clear pending error timeout
    if (errorTimeoutRef.current) {
      clearTimeout(errorTimeoutRef.current);
      errorTimeoutRef.current = null;
    }

    // Close EventSource
    if (eventSourceRef.current) {
      eventSourceRef.current.close();
      eventSourceRef.current = null;
    }

    // Close peer connection
    if (pcRef.current) {
      pcRef.current.close();
      pcRef.current = null;
    }

    // Stop local mic tracks (prevents browser mic indicator staying active)
    if (localStreamRef.current) {
      localStreamRef.current.getTracks().forEach((track) => track.stop());
      localStreamRef.current = null;
    }

    // Stop audio element
    if (audioRef.current) {
      audioRef.current.srcObject = null;
      audioRef.current = null;
    }

    webrtcIdRef.current = '';
  }, []);

  // Cleanup on unmount + page refresh/close
  useEffect(() => {
    const handleBeforeUnload = () => {
      cleanup();
      // Use sendBeacon for reliable delivery during page unload
      const url = `${import.meta.env.VITE_API_URL || ''}/api/voice/disconnect`;
      navigator.sendBeacon(url);
    };

    window.addEventListener('beforeunload', handleBeforeUnload);

    return () => {
      window.removeEventListener('beforeunload', handleBeforeUnload);
      cleanup();
      api.disconnectVoice().catch(() => {});
    };
  }, [cleanup]);

  const connect = useCallback(async () => {
    if (state === 'connecting' || state === 'connected') return;

    setState('connecting');

    try {
      // Always disconnect stale server-side connections first
      // This handles cases where a previous session wasn't cleaned up
      // (page refresh, browser crash, network drop, etc.)
      await api.disconnectVoice().catch(() => {});

      // Get user's microphone
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: {
          channelCount: 1,
          sampleRate: 16000,
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true,
        },
      });
      localStreamRef.current = stream;

      // Create peer connection
      const pc = new RTCPeerConnection({
        iceServers: [], // No STUN/TURN needed for localhost
      });
      pcRef.current = pc;

      // Add mic track
      stream.getTracks().forEach((track) => {
        pc.addTrack(track, stream);
      });

      // Create data channel — required by FastRTC to start audio processing
      pc.createDataChannel('data');

      // Handle remote audio (TTS from server)
      pc.ontrack = (event) => {
        const audio = new Audio();
        audio.srcObject = event.streams[0];
        audio.autoplay = true;
        audioRef.current = audio;
      };

      // Handle connection state changes
      pc.onconnectionstatechange = () => {
        switch (pc.connectionState) {
          case 'connected':
            setState('connected');
            break;
          case 'disconnected':
          case 'failed':
          case 'closed':
            setState('disconnected');
            cleanup();
            break;
        }
      };

      // Create and set local offer
      const offer = await pc.createOffer();
      await pc.setLocalDescription(offer);

      // Wait for ICE gathering to complete
      await new Promise<void>((resolve) => {
        if (pc.iceGatheringState === 'complete') {
          resolve();
        } else {
          pc.onicegatheringstatechange = () => {
            if (pc.iceGatheringState === 'complete') {
              resolve();
            }
          };
          // Timeout after 5s
          setTimeout(resolve, 5000);
        }
      });

      // Generate a unique WebRTC ID for this session
      const webrtcId = crypto.randomUUID();
      webrtcIdRef.current = webrtcId;

      // Send offer to server
      const answer = await api.sendWebRTCOffer({
        sdp: pc.localDescription!.sdp,
        type: pc.localDescription!.type,
        webrtc_id: webrtcId,
      });

      // Set remote answer
      await pc.setRemoteDescription(new RTCSessionDescription(answer));

      // Start SSE for text events
      const eventSource = api.connectVoiceOutputs(webrtcId);
      eventSourceRef.current = eventSource;

      eventSource.addEventListener('transcript', (event) => {
        try {
          const data = JSON.parse(event.data);
          optionsRef.current.onTranscript?.(data.text);
        } catch {
          // ignore parse errors
        }
      });

      eventSource.addEventListener('response', (event) => {
        try {
          const data = JSON.parse(event.data);
          optionsRef.current.onResponse?.(data.text);
        } catch {
          // ignore parse errors
        }
      });

      eventSource.addEventListener('sources', (event) => {
        try {
          const data = JSON.parse(event.data);
          optionsRef.current.onSources?.(data.sources);
        } catch {
          // ignore parse errors
        }
      });

      eventSource.addEventListener('error', (event) => {
        if (event instanceof MessageEvent) {
          try {
            const data = JSON.parse(event.data);
            optionsRef.current.onError?.(data.message);
          } catch {
            // ignore parse errors
          }
        }
      });

      setState('connected');
    } catch (err) {
      console.error('WebRTC connection failed:', err);
      setState('error');
      cleanup();
      optionsRef.current.onError?.(
        err instanceof Error ? err.message : 'WebRTC connection failed'
      );

      // Reset to disconnected after showing error briefly
      errorTimeoutRef.current = setTimeout(() => setState('disconnected'), 3000);
    }
  }, [state, cleanup]);

  const disconnect = useCallback(() => {
    cleanup();
    setState('disconnected');

    // Notify server to close peer connections
    api.disconnectVoice().catch(() => {});
  }, [cleanup]);

  const toggleConnection = useCallback(() => {
    if (state === 'disconnected' || state === 'error') {
      connect();
    } else if (state === 'connected') {
      disconnect();
    }
    // If connecting, ignore toggle
  }, [state, connect, disconnect]);

  return {
    state,
    isAvailable,
    connect,
    disconnect,
    toggleConnection,
  };
}
