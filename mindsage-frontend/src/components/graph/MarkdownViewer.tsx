import { useRef, useEffect, useMemo } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { Prism as SyntaxHighlighter } from 'react-syntax-highlighter';
import { oneDark, oneLight } from 'react-syntax-highlighter/dist/esm/styles/prism';
import { useTheme } from '@/components/ThemeProvider';
import type { VectorDocument } from '@/types';

// ---------------------------------------------------------------------------
// Chunk position finder
// ---------------------------------------------------------------------------

function findChunkPosition(
  content: string,
  chunkText: string | undefined
): { start: number; end: number } | null {
  if (!chunkText || !content) return null;

  const exactIdx = content.indexOf(chunkText);
  if (exactIdx !== -1) {
    return { start: exactIdx, end: exactIdx + chunkText.length };
  }

  // Normalized whitespace match
  const normalize = (s: string) => s.replace(/\s+/g, ' ').trim();
  const normalizedChunk = normalize(chunkText);
  const normalizedContent = normalize(content);
  const normIdx = normalizedContent.indexOf(normalizedChunk);
  if (normIdx !== -1) {
    let origPos = 0;
    let normPos = 0;
    while (origPos < content.length && normPos < normIdx) {
      if (/\s/.test(content[origPos])) {
        if (origPos === 0 || !/\s/.test(content[origPos - 1])) normPos++;
      } else {
        normPos++;
      }
      origPos++;
    }
    const start = origPos;
    let chunkNormPos = 0;
    while (origPos < content.length && chunkNormPos < normalizedChunk.length) {
      if (/\s/.test(content[origPos])) {
        if (origPos === 0 || !/\s/.test(content[origPos - 1])) chunkNormPos++;
      } else {
        chunkNormPos++;
      }
      origPos++;
    }
    return { start, end: origPos };
  }

  return null;
}

// ---------------------------------------------------------------------------
// Code block component for ReactMarkdown
// ---------------------------------------------------------------------------

function CodeBlock({
  inline,
  className,
  children,
  syntaxTheme,
}: {
  inline?: boolean;
  className?: string;
  children: React.ReactNode;
  syntaxTheme: Record<string, any>;
}) {
  const match = /language-(\w+)/.exec(className || '');
  const code = String(children).replace(/\n$/, '');

  if (!inline && match) {
    return (
      <SyntaxHighlighter
        language={match[1]}
        style={syntaxTheme}
        customStyle={{
          margin: 0,
          borderRadius: '0.5rem',
          fontSize: '0.8125rem',
          lineHeight: '1.6',
        }}
        showLineNumbers
      >
        {code}
      </SyntaxHighlighter>
    );
  }

  if (!inline && code.includes('\n')) {
    return (
      <SyntaxHighlighter
        language="text"
        style={syntaxTheme}
        customStyle={{
          margin: 0,
          borderRadius: '0.5rem',
          fontSize: '0.8125rem',
          lineHeight: '1.6',
        }}
      >
        {code}
      </SyntaxHighlighter>
    );
  }

  return (
    <code className="px-1.5 py-0.5 rounded-md bg-muted text-[0.8125rem] font-mono">
      {children}
    </code>
  );
}

// ---------------------------------------------------------------------------
// Highlighted code renderer
// ---------------------------------------------------------------------------

function HighlightedCode({
  content,
  chunkText,
  language,
  syntaxTheme,
  highlightRef,
}: {
  content: string;
  chunkText: string | undefined;
  language: string;
  syntaxTheme: Record<string, any>;
  highlightRef: React.RefObject<HTMLMarkElement | null>;
}) {
  const pos = findChunkPosition(content, chunkText);

  if (!pos) {
    return (
      <SyntaxHighlighter
        language={language}
        style={syntaxTheme}
        customStyle={{ margin: 0, borderRadius: '0.5rem', fontSize: '0.8125rem', lineHeight: '1.6' }}
        showLineNumbers
      >
        {content}
      </SyntaxHighlighter>
    );
  }

  const lines = content.split('\n');
  let charCount = 0;
  const startLine = lines.findIndex(line => {
    charCount += line.length + 1;
    return charCount > pos.start;
  });
  charCount = 0;
  const endLine = lines.findIndex(line => {
    charCount += line.length + 1;
    return charCount >= pos.end;
  });

  const highlightLines = new Set<number>();
  for (let i = Math.max(0, startLine); i <= Math.min(lines.length - 1, endLine); i++) {
    highlightLines.add(i);
  }

  return (
    <div className="relative">
      <mark ref={highlightRef} className="absolute" style={{ top: `${startLine * 1.5}em` }} />
      <SyntaxHighlighter
        language={language}
        style={syntaxTheme}
        customStyle={{ margin: 0, borderRadius: '0.5rem', fontSize: '0.8125rem', lineHeight: '1.6' }}
        wrapLines
        lineProps={(lineNumber: number) => {
          if (highlightLines.has(lineNumber - 1)) {
            return {
              style: {
                backgroundColor: 'hsl(var(--primary) / 0.08)',
                borderLeft: '3px solid hsl(var(--primary) / 0.4)',
                paddingLeft: '0.5em',
                display: 'block',
              },
            };
          }
          return { style: { display: 'block' } };
        }}
        showLineNumbers
      >
        {content}
      </SyntaxHighlighter>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Highlighted Markdown renderer
// ---------------------------------------------------------------------------

function HighlightedMarkdown({
  content,
  chunkText,
  syntaxTheme,
  highlightRef,
}: {
  content: string;
  chunkText: string | undefined;
  syntaxTheme: Record<string, any>;
  highlightRef: React.RefObject<HTMLMarkElement | null>;
}) {
  const pos = findChunkPosition(content, chunkText);

  const markdownComponents = useMemo(
    () => ({
      code({ inline, className, children }: any) {
        return (
          <CodeBlock inline={inline} className={className} syntaxTheme={syntaxTheme}>
            {children}
          </CodeBlock>
        );
      },
      // Tables get nice styling via prose, but add horizontal scroll wrapper
      table({ children }: any) {
        return (
          <div className="overflow-x-auto -mx-1">
            <table>{children}</table>
          </div>
        );
      },
      // Images get rounded corners + shadow
      img({ src, alt, ...props }: any) {
        return (
          <img
            src={src}
            alt={alt}
            className="rounded-lg shadow-sm border border-border/50 max-w-full"
            loading="lazy"
            {...props}
          />
        );
      },
      // Blockquotes get a subtle left border accent
      blockquote({ children }: any) {
        return (
          <blockquote className="border-l-2 border-primary/30 pl-4 italic text-muted-foreground not-italic">
            {children}
          </blockquote>
        );
      },
      // Horizontal rules
      hr() {
        return <hr className="border-border/50 my-6" />;
      },
      // Links open in new tab
      a({ href, children }: any) {
        return (
          <a
            href={href}
            target="_blank"
            rel="noopener noreferrer"
            className="text-primary underline decoration-primary/30 underline-offset-2 hover:decoration-primary/60 transition-colors"
          >
            {children}
          </a>
        );
      },
    }),
    [syntaxTheme]
  );

  if (!pos) {
    return (
      <div className="md-viewer">
        <ReactMarkdown remarkPlugins={[remarkGfm]} components={markdownComponents}>
          {content}
        </ReactMarkdown>
      </div>
    );
  }

  // Split content into before, chunk, and after portions
  const before = content.slice(0, pos.start);
  const chunk = content.slice(pos.start, pos.end);
  const after = content.slice(pos.end);

  return (
    <div className="md-viewer">
      {before && (
        <ReactMarkdown remarkPlugins={[remarkGfm]} components={markdownComponents}>
          {before}
        </ReactMarkdown>
      )}
      <mark
        ref={highlightRef}
        className="block bg-primary/[0.06] border-l-2 border-primary/40 pl-3 -ml-3 pr-1 py-1 rounded-r-md"
      >
        <ReactMarkdown remarkPlugins={[remarkGfm]} components={markdownComponents}>
          {chunk}
        </ReactMarkdown>
      </mark>
      {after && (
        <ReactMarkdown remarkPlugins={[remarkGfm]} components={markdownComponents}>
          {after}
        </ReactMarkdown>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main DocumentContentViewer
// ---------------------------------------------------------------------------

interface DocumentContentViewerProps {
  doc: VectorDocument;
  chunkText?: string;
}

export function DocumentContentViewer({ doc, chunkText }: DocumentContentViewerProps) {
  const { resolvedTheme } = useTheme();
  const highlightRef = useRef<HTMLMarkElement>(null);
  const syntaxTheme = resolvedTheme === 'dark' ? oneDark : oneLight;

  // Auto-scroll to highlighted chunk
  useEffect(() => {
    if (chunkText && highlightRef.current) {
      const timer = setTimeout(() => {
        highlightRef.current?.scrollIntoView({ behavior: 'smooth', block: 'center' });
      }, 150);
      return () => clearTimeout(timer);
    }
  }, [doc.id, chunkText]);

  // Code files get syntax highlighting
  if (doc.fileType === 'code') {
    return (
      <HighlightedCode
        content={doc.content}
        chunkText={chunkText}
        language={doc.extension}
        syntaxTheme={syntaxTheme}
        highlightRef={highlightRef}
      />
    );
  }

  // Everything else (pdf, txt, md, doc, etc.) goes through the markdown renderer.
  // Markdown is a superset of plain text, so this is safe for all content —
  // plain text renders as paragraphs, while content with markdown formatting
  // (headings, lists, tables) gets properly styled.
  return (
    <HighlightedMarkdown
      content={doc.content}
      chunkText={chunkText}
      syntaxTheme={syntaxTheme}
      highlightRef={highlightRef}
    />
  );
}
