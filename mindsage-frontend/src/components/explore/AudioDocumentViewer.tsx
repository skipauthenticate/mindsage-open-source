/**
 * AudioDocumentViewer - Display audio documents with transcript and PII highlighting
 *
 * Features:
 * - Audio player with playback controls
 * - Transcript tabs (Original / Redacted)
 * - PII region highlighting with click-to-seek
 * - Duration and format display
 */

import { useState, useRef, useEffect, useCallback } from 'react';
import { Play, Pause, Volume2, VolumeX, Clock, FileAudio, Shield, ShieldAlert } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { ScrollArea } from '@/components/ui/scroll-area';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { Slider } from '@/components/ui/slider';
import type { VectorDocument, AudioPIIRegion } from '@/types';

interface AudioDocumentViewerProps {
  document: VectorDocument;
}

// Format seconds to MM:SS
function formatTime(seconds: number): string {
  const mins = Math.floor(seconds / 60);
  const secs = Math.floor(seconds % 60);
  return `${mins}:${secs.toString().padStart(2, '0')}`;
}

// PII type to color mapping
const PII_COLORS: Record<string, string> = {
  PERSON: 'bg-red-200 dark:bg-red-900/50 text-red-800 dark:text-red-200',
  EMAIL_ADDRESS: 'bg-blue-200 dark:bg-blue-900/50 text-blue-800 dark:text-blue-200',
  PHONE_NUMBER: 'bg-green-200 dark:bg-green-900/50 text-green-800 dark:text-green-200',
  LOCATION: 'bg-purple-200 dark:bg-purple-900/50 text-purple-800 dark:text-purple-200',
  DATE_TIME: 'bg-yellow-200 dark:bg-yellow-900/50 text-yellow-800 dark:text-yellow-200',
  US_SSN: 'bg-orange-200 dark:bg-orange-900/50 text-orange-800 dark:text-orange-200',
  CREDIT_CARD: 'bg-pink-200 dark:bg-pink-900/50 text-pink-800 dark:text-pink-200',
  DEFAULT: 'bg-gray-200 dark:bg-gray-700 text-gray-800 dark:text-gray-200',
};

function getPiiColor(piiType: string): string {
  return PII_COLORS[piiType] || PII_COLORS.DEFAULT;
}

// Clickable PII region component
function PiiRegionBadge({
  region,
  onSeek,
}: {
  region: AudioPIIRegion;
  onSeek: (time: number) => void;
}) {
  return (
    <button
      onClick={() => onSeek(region.startTime)}
      className={`inline-flex items-center gap-1 px-2 py-0.5 rounded text-xs font-medium transition-colors hover:ring-2 hover:ring-offset-1 cursor-pointer ${getPiiColor(region.piiType)}`}
      title={`Click to seek to ${formatTime(region.startTime)} - ${region.piiType}`}
    >
      <Clock className="h-3 w-3" />
      {formatTime(region.startTime)}
      <span className="mx-0.5">|</span>
      {region.piiType}
    </button>
  );
}

// Vector store URL for audio serving
const VECTOR_STORE_URL = import.meta.env.VITE_VECTOR_STORE_URL || 'http://localhost:8085';

export function AudioDocumentViewer({ document }: AudioDocumentViewerProps) {
  const audioRef = useRef<HTMLAudioElement>(null);
  const [isPlaying, setIsPlaying] = useState(false);
  const [isMuted, setIsMuted] = useState(false);
  const [currentTime, setCurrentTime] = useState(0);
  const [duration, setDuration] = useState(0);
  const [activeTab, setActiveTab] = useState<'original' | 'redacted'>('original');

  const audioMeta = document.audioMetadata;

  // Build audio URL from audioId — switches between original and redacted
  const audioUrl = audioMeta?.audioId
    ? `${VECTOR_STORE_URL}/api/audio/serve/${audioMeta.audioId}?type=${activeTab}`
    : undefined;

  // Track last loaded URL to avoid re-loading same source
  const lastLoadedUrlRef = useRef<string | undefined>(undefined);

  // Handle audio source changes
  useEffect(() => {
    const audio = audioRef.current;
    if (!audio) return;

    // Only update source if URL actually changed
    if (audioUrl && audioUrl !== lastLoadedUrlRef.current) {
      // Pause any current playback first
      audio.pause();
      setIsPlaying(false);
      setCurrentTime(0);

      // Set new source
      audio.src = audioUrl;
      audio.load();
      lastLoadedUrlRef.current = audioUrl;
    } else if (!audioUrl && lastLoadedUrlRef.current) {
      // Clear source if URL became undefined
      audio.pause();
      audio.removeAttribute('src');
      lastLoadedUrlRef.current = undefined;
      setIsPlaying(false);
      setCurrentTime(0);
    }
  }, [audioUrl]);

  // Set up event listeners (separate effect to avoid re-attaching on URL change)
  useEffect(() => {
    const audio = audioRef.current;
    if (!audio) return;

    const handleTimeUpdate = () => setCurrentTime(audio.currentTime);
    const handleDurationChange = () => {
      if (!isNaN(audio.duration) && isFinite(audio.duration)) {
        setDuration(audio.duration);
      }
    };
    const handleEnded = () => setIsPlaying(false);
    const handlePlay = () => setIsPlaying(true);
    const handlePause = () => setIsPlaying(false);

    audio.addEventListener('timeupdate', handleTimeUpdate);
    audio.addEventListener('durationchange', handleDurationChange);
    audio.addEventListener('loadedmetadata', handleDurationChange);
    audio.addEventListener('ended', handleEnded);
    audio.addEventListener('play', handlePlay);
    audio.addEventListener('pause', handlePause);

    return () => {
      audio.removeEventListener('timeupdate', handleTimeUpdate);
      audio.removeEventListener('durationchange', handleDurationChange);
      audio.removeEventListener('loadedmetadata', handleDurationChange);
      audio.removeEventListener('ended', handleEnded);
      audio.removeEventListener('play', handlePlay);
      audio.removeEventListener('pause', handlePause);
    };
  }, []);

  // Play/Pause toggle with proper Promise handling
  const togglePlay = useCallback(() => {
    const audio = audioRef.current;
    if (!audio || !audioUrl) return;

    if (isPlaying) {
      audio.pause();
    } else {
      // Check if audio is ready to play (readyState >= 2 means HAVE_CURRENT_DATA)
      if (audio.readyState < 2) {
        // Audio not ready yet, wait for canplay event
        const handleCanPlay = () => {
          audio.removeEventListener('canplay', handleCanPlay);
          const playPromise = audio.play();
          if (playPromise !== undefined) {
            playPromise.catch((error) => {
              if (error.name !== 'AbortError') {
                console.error('Audio playback error:', error);
              }
            });
          }
        };
        audio.addEventListener('canplay', handleCanPlay);
        audio.load(); // Trigger loading if needed
      } else {
        // Audio is ready, play immediately
        const playPromise = audio.play();
        if (playPromise !== undefined) {
          playPromise.catch((error) => {
            // Ignore AbortError - it just means playback was interrupted
            if (error.name !== 'AbortError') {
              console.error('Audio playback error:', error);
            }
          });
        }
      }
    }
    // State is updated by play/pause event handlers
  }, [isPlaying, audioUrl]);

  // Mute toggle
  const toggleMute = useCallback(() => {
    const audio = audioRef.current;
    if (!audio) return;

    audio.muted = !isMuted;
    setIsMuted(!isMuted);
  }, [isMuted]);

  // Seek to time with proper Promise handling
  const seekTo = useCallback((time: number) => {
    const audio = audioRef.current;
    if (!audio || !audioUrl) return;

    // Wait for audio to be seekable
    if (audio.readyState < 1) {
      // Not enough data yet, wait for loadedmetadata
      const handleLoaded = () => {
        audio.removeEventListener('loadedmetadata', handleLoaded);
        audio.currentTime = time;
        setCurrentTime(time);
        // Auto-play after seek
        const playPromise = audio.play();
        if (playPromise !== undefined) {
          playPromise.catch((error) => {
            if (error.name !== 'AbortError') {
              console.error('Audio playback error:', error);
            }
          });
        }
      };
      audio.addEventListener('loadedmetadata', handleLoaded);
      audio.load();
    } else {
      audio.currentTime = time;
      setCurrentTime(time);
      // Auto-play when seeking from PII regions
      if (!isPlaying) {
        const playPromise = audio.play();
        if (playPromise !== undefined) {
          playPromise.catch((error) => {
            if (error.name !== 'AbortError') {
              console.error('Audio playback error:', error);
            }
          });
        }
      }
    }
  }, [isPlaying, audioUrl]);

  // Handle slider change
  const handleSliderChange = useCallback((value: number[]) => {
    const audio = audioRef.current;
    if (!audio) return;

    const newTime = value[0];
    audio.currentTime = newTime;
    setCurrentTime(newTime);
  }, []);

  // Get display duration (from metadata or audio element)
  const displayDuration = audioMeta?.durationSeconds || duration || 0;

  // Get transcripts
  const originalTranscript = audioMeta?.originalTranscript || document.content;
  const redactedTranscript = audioMeta?.redactedTranscript || document.content;
  const hasPii = audioMeta?.hasPii || false;
  const piiRegions = audioMeta?.piiRegions || [];
  const piiTypesFound = audioMeta?.piiTypesFound || [];

  return (
    <div className="h-full flex flex-col">
      {/* Header with metadata */}
      <div className="p-4 border-b border-border space-y-3">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <FileAudio className="h-5 w-5 text-muted-foreground" />
            <span className="font-medium">{document.filename}</span>
          </div>
          <div className="flex items-center gap-2">
            {hasPii ? (
              <Badge variant="destructive" className="gap-1">
                <ShieldAlert className="h-3 w-3" />
                PII Detected
              </Badge>
            ) : (
              <Badge variant="secondary" className="gap-1">
                <Shield className="h-3 w-3" />
                No PII
              </Badge>
            )}
          </div>
        </div>

        {/* Audio metadata */}
        <div className="flex items-center gap-4 text-xs text-muted-foreground">
          <span>{audioMeta?.format?.toUpperCase() || document.extension.toUpperCase()}</span>
          <span>{formatTime(displayDuration)}</span>
          {audioMeta?.sampleRate && <span>{audioMeta.sampleRate} Hz</span>}
          {audioMeta?.channels && <span>{audioMeta.channels === 1 ? 'Mono' : 'Stereo'}</span>}
          {audioMeta?.wordCount && <span>{audioMeta.wordCount} words</span>}
        </div>

        {/* Audio Player */}
        <div className="space-y-2">
          {/* Audio element - src is set programmatically in useEffect */}
          <audio ref={audioRef} preload="metadata" crossOrigin="anonymous" />

          {/* Player controls */}
          <div className="flex items-center gap-3">
            <Button
              variant="outline"
              size="icon"
              className="h-10 w-10"
              onClick={togglePlay}
            >
              {isPlaying ? (
                <Pause className="h-4 w-4" />
              ) : (
                <Play className="h-4 w-4" />
              )}
            </Button>

            <div className="flex-1 space-y-1">
              <Slider
                value={[currentTime]}
                max={displayDuration || 100}
                step={0.1}
                onValueChange={handleSliderChange}
                className="cursor-pointer"
              />
              <div className="flex justify-between text-xs text-muted-foreground">
                <span>{formatTime(currentTime)}</span>
                <span>{formatTime(displayDuration)}</span>
              </div>
            </div>

            <Button
              variant="ghost"
              size="icon"
              className="h-8 w-8"
              onClick={toggleMute}
            >
              {isMuted ? (
                <VolumeX className="h-4 w-4" />
              ) : (
                <Volume2 className="h-4 w-4" />
              )}
            </Button>
          </div>
        </div>

        {/* PII Types Found */}
        {piiTypesFound.length > 0 && (
          <div className="flex items-center gap-2 flex-wrap">
            <span className="text-xs text-muted-foreground">PII found:</span>
            {piiTypesFound.map((type) => (
              <Badge
                key={type}
                variant="outline"
                className={`text-xs ${getPiiColor(type)}`}
              >
                {type}
              </Badge>
            ))}
          </div>
        )}
      </div>

      {/* Transcript Tabs */}
      <Tabs
        value={activeTab}
        onValueChange={(v) => setActiveTab(v as 'original' | 'redacted')}
        className="flex-1 flex flex-col"
      >
        <div className="px-4 pt-2 border-b border-border">
          <TabsList className="h-9">
            <TabsTrigger value="original" className="text-xs">
              Original Transcript
            </TabsTrigger>
            <TabsTrigger value="redacted" className="text-xs">
              Redacted Transcript
            </TabsTrigger>
          </TabsList>
        </div>

        <ScrollArea className="flex-1">
          <TabsContent value="original" className="p-4 m-0">
            <div className="space-y-4">
              {/* PII Regions with click-to-seek */}
              {piiRegions.length > 0 && (
                <div className="p-3 rounded-lg bg-muted/50 space-y-2">
                  <p className="text-xs font-medium text-muted-foreground">
                    Click to seek to PII locations:
                  </p>
                  <div className="flex flex-wrap gap-2">
                    {piiRegions.map((region, idx) => (
                      <PiiRegionBadge
                        key={`${region.startTime}-${idx}`}
                        region={region}
                        onSeek={seekTo}
                      />
                    ))}
                  </div>
                </div>
              )}

              {/* Original transcript */}
              <pre className="text-sm whitespace-pre-wrap font-sans leading-relaxed">
                {originalTranscript}
              </pre>
            </div>
          </TabsContent>

          <TabsContent value="redacted" className="p-4 m-0">
            <div className="space-y-4">
              {hasPii && (
                <div className="p-3 rounded-lg bg-muted/50">
                  <p className="text-xs text-muted-foreground">
                    PII has been replaced with [TYPE] tags. This version is used for LLM context and embeddings.
                  </p>
                </div>
              )}

              {/* Redacted transcript */}
              <pre className="text-sm whitespace-pre-wrap font-sans leading-relaxed">
                {redactedTranscript}
              </pre>
            </div>
          </TabsContent>
        </ScrollArea>
      </Tabs>
    </div>
  );
}
