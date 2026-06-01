import { useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { ChevronDown, FileText, ChevronRight } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from '@/components/ui/tooltip';
import type { ChatContext, PerturbedValue } from '@/lib/api';

/**
 * Maps PII entity types to user-friendly category names.
 * This improves UX by showing meaningful categories instead of technical type names,
 * and reduces confusion when Presidio has false positives (e.g., detecting a number as DATE_TIME).
 */
function getPiiDisplayName(piiType: string): string {
  const categoryMap: Record<string, string> = {
    // Personal identifiers
    PERSON: 'personal name',
    NRP: 'personal identifier',

    // Contact information
    PHONE_NUMBER: 'contact info',
    EMAIL_ADDRESS: 'contact info',

    // Financial information
    CREDIT_CARD: 'financial info',
    US_BANK_NUMBER: 'financial info',
    IBAN_CODE: 'financial info',

    // Government IDs
    US_SSN: 'government ID',
    US_ITIN: 'government ID',
    US_PASSPORT: 'government ID',
    AU_TFN: 'government ID',
    IN_AADHAAR: 'government ID',
    IN_PAN: 'government ID',
    SG_NRIC_FIN: 'government ID',

    // Location
    LOCATION: 'location',

    // Network/Technical
    IP_ADDRESS: 'network info',
    URL: 'web address',
    DOMAIN_NAME: 'web address',

    // DATE_TIME intentionally omitted - falls back to "sensitive data"
    // since it often has false positives
  };

  return categoryMap[piiType] || 'sensitive data';
}

interface SourcesListProps {
  sources: ChatContext[];
  className?: string;
}

/**
 * Renders text with privacy-protected spans highlighted with dotted underlines.
 * Uses simple string matching to find perturbed values in the text.
 */
function HighlightedExcerpt({ text, spans }: { text: string; spans?: PerturbedValue[] }) {
  if (!spans || spans.length === 0) {
    return <>{text}</>;
  }

  // Get unique perturbed values sorted by length (longest first to avoid partial matches)
  const uniqueValues = [...new Map(
    spans.map(s => [s.perturbed_value.toLowerCase(), s])
  ).values()].sort((a, b) => b.perturbed_value.length - a.perturbed_value.length);

  // Find all matches in the text
  interface Match {
    start: number;
    end: number;
    span: PerturbedValue;
  }
  const matches: Match[] = [];
  const textLower = text.toLowerCase();

  for (const span of uniqueValues) {
    const valueLower = span.perturbed_value.toLowerCase();
    let searchStart = 0;

    while (true) {
      const idx = textLower.indexOf(valueLower, searchStart);
      if (idx === -1) break;

      // Check if this position overlaps with existing matches
      const end = idx + span.perturbed_value.length;
      const overlaps = matches.some(m =>
        (idx >= m.start && idx < m.end) || (end > m.start && end <= m.end)
      );

      if (!overlaps) {
        matches.push({ start: idx, end, span });
      }
      searchStart = idx + 1;
    }
  }

  // Sort matches by position
  matches.sort((a, b) => a.start - b.start);

  if (matches.length === 0) {
    return <>{text}</>;
  }

  // Build elements
  const elements: React.ReactNode[] = [];
  let lastEnd = 0;

  matches.forEach((match, index) => {
    // Add text before this match
    if (match.start > lastEnd) {
      elements.push(text.slice(lastEnd, match.start));
    }

    // Add the highlighted span (use original case from text)
    const matchText = text.slice(match.start, match.end);
    elements.push(
      <TooltipProvider key={`span-${index}`} delayDuration={300}>
        <Tooltip>
          <TooltipTrigger asChild>
            <span
              className="border-b border-dotted border-primary/60 cursor-help"
            >
              {matchText}
            </span>
          </TooltipTrigger>
          <TooltipContent side="top" className="text-xs">
            <p>Privacy-protected {getPiiDisplayName(match.span.pii_type)}</p>
            {match.span.is_lprag && (
              <p className="text-muted-foreground">Replaced with similar value</p>
            )}
          </TooltipContent>
        </Tooltip>
      </TooltipProvider>
    );

    lastEnd = match.end;
  });

  // Add remaining text
  if (lastEnd < text.length) {
    elements.push(text.slice(lastEnd));
  }

  return <>{elements}</>;
}

export function SourcesList({ sources, className }: SourcesListProps) {
  const [isExpanded, setIsExpanded] = useState(false);
  const [expandedSourceId, setExpandedSourceId] = useState<number | null>(null);

  if (!sources || sources.length === 0) return null;

  const toggleSourceExpand = (sourceId: number) => {
    setExpandedSourceId(prev => prev === sourceId ? null : sourceId);
  };

  return (
    <div className={className}>
      <Button
        variant="ghost"
        size="sm"
        className="h-7 px-2 text-xs text-muted-foreground hover:text-foreground gap-1"
        onClick={() => setIsExpanded(!isExpanded)}
      >
        <FileText className="h-3 w-3" />
        {sources.length} source{sources.length !== 1 ? 's' : ''}
        <ChevronDown className={`h-3 w-3 transition-transform ${isExpanded ? 'rotate-180' : ''}`} />
      </Button>

      <AnimatePresence>
        {isExpanded && (
          <motion.div
            initial={{ opacity: 0, height: 0 }}
            animate={{ opacity: 1, height: 'auto' }}
            exit={{ opacity: 0, height: 0 }}
            transition={{ duration: 0.2 }}
            className="overflow-hidden"
          >
            <div className="mt-2 space-y-2 pl-2 border-l-2 border-muted">
              {sources.map((source, index) => {
                const sourceKey = source.id ?? index;
                const isSourceExpanded = expandedSourceId === sourceKey;
                return (
                  <motion.div
                    key={sourceKey}
                    initial={{ opacity: 0, x: -10 }}
                    animate={{ opacity: 1, x: 0 }}
                    transition={{ delay: index * 0.05 }}
                    className="rounded bg-muted/50 overflow-hidden"
                  >
                    {/* Clickable header */}
                    <button
                      onClick={() => toggleSourceExpand(sourceKey)}
                      className="w-full p-2 text-left hover:bg-muted/80 transition-colors flex items-start gap-2"
                    >
                      <ChevronRight
                        className={`h-3 w-3 mt-0.5 shrink-0 text-muted-foreground transition-transform ${isSourceExpanded ? 'rotate-90' : ''}`}
                      />
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center justify-between mb-1">
                          <span className="text-xs font-medium text-foreground truncate flex-1 min-w-0">
                            {source.filename || `Document ${source.id}`}
                          </span>
                          {source.score !== null && source.score !== undefined && (
                            <Badge variant="outline" className="text-[10px] px-1.5 py-0 shrink-0 ml-2">
                              {(source.score * 100).toFixed(0)}%
                            </Badge>
                          )}
                        </div>
                        {!isSourceExpanded && (
                          <p className="text-xs text-muted-foreground line-clamp-2">
                            <HighlightedExcerpt text={source.excerpt} spans={source.perturbed_values} />
                          </p>
                        )}
                      </div>
                    </button>

                    {/* Expanded content - no height animation to allow scrolling */}
                    {isSourceExpanded && (
                      <div className="px-2 pb-2 pt-0">
                        <div
                          className="bg-background/50 rounded border border-border/50 overflow-y-auto"
                          style={{ maxHeight: '300px' }}
                        >
                          <div className="p-3 text-xs text-muted-foreground whitespace-pre-wrap leading-relaxed break-words">
                            <HighlightedExcerpt text={source.excerpt} spans={source.perturbed_values} />
                          </div>
                        </div>
                        <p className="text-[10px] text-muted-foreground/70 mt-1.5 italic">
                          This is the full context sent to the LLM for this source
                        </p>
                      </div>
                    )}
                  </motion.div>
                );
              })}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
