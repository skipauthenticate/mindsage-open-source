import { useState, useEffect } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { Search, FileText, FileCode, FileJson, FileAudio, Image as ImageIcon, Trash2, ChevronLeft, ChevronRight, Sparkles, Shield, ShieldAlert, Loader2 } from 'lucide-react';
import { Input } from '@/components/ui/input';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { ScrollArea } from '@/components/ui/scroll-area';
import { Skeleton } from '@/components/ui/skeleton';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { ResizablePanelGroup, ResizablePanel, ResizableHandle } from '@/components/ui/resizable';
import { AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent, AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle, AlertDialogTrigger } from '@/components/ui/alert-dialog';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { listVectorDocuments, getVectorDocument, deleteVectorDocument, api, getDisplayName } from '@/lib/api';
import { DocumentContentViewer } from '@/components/graph/MarkdownViewer';
import type { VectorDocument, VectorSearchResult } from '@/types';
import { AudioDocumentViewer } from './AudioDocumentViewer';

// Vector store URL for image serving
const VECTOR_STORE_URL = import.meta.env.VITE_VECTOR_STORE_URL || 'http://localhost:8085';

const fileIcons: Record<string, { icon: typeof FileText; color: string }> = {
  code: { icon: FileCode, color: 'text-info' },
  document: { icon: FileText, color: 'text-destructive' },
  data: { icon: FileJson, color: 'text-success' },
  text: { icon: FileText, color: 'text-muted-foreground' },
  audio: { icon: FileAudio, color: 'text-primary' },
  image: { icon: ImageIcon, color: 'text-warning' },
};

function getScoreColor(score: number) {
  if (score >= 0.8) return 'bg-success/20 text-success';
  if (score >= 0.6) return 'bg-warning/20 text-warning';
  return 'bg-muted text-muted-foreground';
}

function getMethodBadge(method: string) {
  switch (method) {
    case 'ai':
      return { label: 'AI Extracted', className: 'bg-badge-ai/20 text-badge-ai' };
    case 'indexed':
      return { label: 'Pre-indexed', className: 'bg-badge-indexed/20 text-badge-indexed' };
    default:
      return { label: 'Context Window', className: 'bg-muted text-muted-foreground' };
  }
}

function getFileType(filename: string): 'code' | 'document' | 'data' | 'text' | 'audio' | 'image' {
  const ext = getExtension(filename).toLowerCase();
  const codeExts = ['ts', 'tsx', 'js', 'jsx', 'py', 'java', 'cpp', 'c', 'h', 'rs', 'go', 'rb', 'php'];
  const docExts = ['md', 'txt', 'doc', 'docx', 'pdf'];
  const dataExts = ['json', 'csv', 'xml', 'yaml', 'yml'];
  const audioExts = ['wav', 'mp3', 'flac', 'ogg', 'm4a', 'wma', 'aac', 'webm'];
  const imageExts = ['jpg', 'jpeg', 'png', 'gif', 'webp', 'bmp', 'tiff', 'heic'];

  if (codeExts.includes(ext)) return 'code';
  if (docExts.includes(ext)) return 'document';
  if (dataExts.includes(ext)) return 'data';
  if (audioExts.includes(ext)) return 'audio';
  if (imageExts.includes(ext)) return 'image';
  return 'text';
}

function getExtension(filename: string): string {
  const parts = filename.split('.');
  return parts.length > 1 ? parts[parts.length - 1] : '';
}

// Group search results by document, keeping the highest scoring chunk for each
function groupResultsByDocument(results: VectorSearchResult[]): VectorSearchResult[] {
  const documentMap = new Map<string, VectorSearchResult>();

  for (const result of results) {
    const existing = documentMap.get(result.filename);
    if (!existing || result.score > existing.score) {
      documentMap.set(result.filename, result);
    }
  }

  // Sort by score descending
  return Array.from(documentMap.values()).sort((a, b) => b.score - a.score);
}

function SearchResultItem({
  result,
  isSelected,
  onClick
}: {
  result: VectorSearchResult;
  isSelected: boolean;
  onClick: () => void;
}) {
  const methodBadge = getMethodBadge(result.excerptMethod);

  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      onClick={onClick}
      className={`p-3 rounded-lg cursor-pointer transition-colors ${
        isSelected ? 'bg-accent' : 'hover:bg-accent/50'
      }`}
    >
      <div className="flex items-start justify-between gap-2 mb-2">
        <div className="flex items-center gap-2 min-w-0">
          <FileText className="h-4 w-4 text-muted-foreground shrink-0" />
          <span className="text-sm font-medium truncate">{result.filename}</span>
        </div>
        <Badge className={`shrink-0 text-xs ${getScoreColor(result.score)}`}>
          {Math.round(result.score * 100)}%
        </Badge>
      </div>
      <p className="text-xs text-muted-foreground line-clamp-2 mb-2">
        {result.excerpt}
      </p>
      <div className="flex items-center gap-1 flex-wrap">
        <Badge variant="outline" className={`text-xs ${methodBadge.className}`}>
          {methodBadge.label}
        </Badge>
        {result.topics.slice(0, 1).map(topic => (
          <Badge key={topic} variant="secondary" className="text-xs">
            {topic}
          </Badge>
        ))}
      </div>
    </motion.div>
  );
}

function DocumentListItem({
  doc,
  isSelected,
  onClick
}: {
  doc: VectorDocument;
  isSelected: boolean;
  onClick: () => void;
}) {
  const { icon: Icon, color } = fileIcons[doc.fileType] || fileIcons.text;

  // Sort topics so primary topic comes first
  const sortedTopics = [...doc.topics].sort((a, b) => {
    if (a === doc.primaryTopic) return -1;
    if (b === doc.primaryTopic) return 1;
    return 0;
  });

  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      onClick={onClick}
      className={`p-3 rounded-lg cursor-pointer transition-colors ${
        isSelected ? 'bg-accent' : 'hover:bg-accent/50'
      }`}
    >
      <div className="flex items-start gap-3">
        <Icon className={`h-4 w-4 mt-0.5 shrink-0 ${color}`} />
        <div className="min-w-0 flex-1">
          <p className="text-sm font-medium truncate">{doc.filename}</p>
          <div className="flex gap-1 mt-1 flex-wrap">
            {sortedTopics.map(topic => (
              <Badge
                key={topic}
                variant={topic === doc.primaryTopic ? "default" : "secondary"}
                className={`text-xs ${topic === doc.primaryTopic ? 'bg-primary text-primary-foreground' : ''}`}
              >
                {topic}
              </Badge>
            ))}
          </div>
          <p className="text-xs text-muted-foreground mt-1">
            {new Date(doc.createdAt).toLocaleDateString()}
          </p>
        </div>
      </div>
    </motion.div>
  );
}

interface DocumentViewerProps {
  searchQuery?: string;
  searchResults?: VectorSearchResult[];
  isSearching?: boolean;
  selectedTopic?: string;
}

export function DocumentViewer({
  searchQuery = '',
  searchResults,
  isSearching = false,
  selectedTopic = 'all'
}: DocumentViewerProps) {
  const [page, setPage] = useState(1);
  const [localFilter, setLocalFilter] = useState('');
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const queryClient = useQueryClient();
  const pageSize = 10;

  // Reset page when topic filter changes
  useEffect(() => {
    setPage(1);
  }, [selectedTopic]);

  // Determine if we're showing search results or browsing documents
  const hasSearchResults = searchResults && searchResults.length > 0;
  const hasTopicFilter = selectedTopic && selectedTopic !== 'all';

  // Fetch documents - either all documents or filtered by topic
  const { data: docList, isLoading: listLoading } = useQuery({
    queryKey: ['documents', page, pageSize, selectedTopic],
    queryFn: async () => {
      if (hasTopicFilter) {
        // Fetch documents filtered by topic
        const result = await api.getDocumentsByTopic(selectedTopic, page, pageSize);
        return {
          documents: result.documents.map(d => ({
            id: d.id,
            filename: getDisplayName(d.id, d.metadata),
            content: d.text,
            topics: d.topics || [],
            primaryTopic: d.primary_topic,
            source: d.metadata?.source || 'unknown',
            createdAt: d.created_at,
            wordCount: d.text.split(/\s+/).length,
            fileType: getFileType(d.metadata?.filename || d.metadata?.parent_filename || ''),
            extension: getExtension(d.metadata?.filename || d.metadata?.parent_filename || ''),
          })),
          total: result.total,
        };
      }
      return listVectorDocuments(page, pageSize);
    },
    enabled: !hasSearchResults, // Only fetch when not showing search results
  });

  const { data: selectedDoc } = useQuery({
    queryKey: ['document', selectedId],
    queryFn: () => selectedId ? getVectorDocument(selectedId) : null,
    enabled: !!selectedId,
    // Auto-refresh every 2 seconds while PII redaction is pending
    refetchInterval: (query) => query.state.data?.redactionPending ? 2000 : false,
  });

  const deleteMutation = useMutation({
    mutationFn: deleteVectorDocument,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['documents'] });
      setSelectedId(null);
    },
  });

  // Group search results by document (deduplicate chunks from same doc)
  const groupedSearchResults = searchResults ? groupResultsByDocument(searchResults) : undefined;

  // Filter search results or documents by local filter
  const filteredSearchResults = groupedSearchResults?.filter(result =>
    result.filename.toLowerCase().includes(localFilter.toLowerCase()) ||
    result.excerpt.toLowerCase().includes(localFilter.toLowerCase())
  );

  const filteredDocs = docList?.documents.filter(doc =>
    doc.filename.toLowerCase().includes(localFilter.toLowerCase()) ||
    doc.topics.some(t => t.toLowerCase().includes(localFilter.toLowerCase())) ||
    doc.content.toLowerCase().includes(localFilter.toLowerCase())
  );

  const totalPages = Math.ceil((docList?.total || 0) / pageSize);

  const displayCount = hasSearchResults
    ? filteredSearchResults?.length || 0
    : filteredDocs?.length || 0;
  const totalCount = hasSearchResults
    ? searchResults?.length || 0
    : docList?.total || 0;

  return (
    <div className="h-full rounded-lg border border-border overflow-hidden">
      <ResizablePanelGroup direction="horizontal">
        <ResizablePanel defaultSize={35} minSize={25} maxSize={50}>
          <div className="h-full flex flex-col bg-card">
            <div className="p-3 border-b border-border space-y-2">
              <div className="relative">
                <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
                <Input
                  placeholder={hasSearchResults ? "Refine results..." : "Filter documents..."}
                  value={localFilter}
                  onChange={(e) => setLocalFilter(e.target.value)}
                  className="pl-9 h-9"
                />
              </div>
              <div className="flex items-center justify-between">
                <p className="text-xs text-muted-foreground">
                  {hasSearchResults
                    ? `${displayCount} results`
                    : `${displayCount} of ${totalCount} documents`
                  }
                </p>
                {hasSearchResults && (
                  <Badge variant="outline" className="text-xs gap-1">
                    <Sparkles className="h-3 w-3" />
                    Semantic
                  </Badge>
                )}
              </div>
            </div>

            <ScrollArea className="flex-1">
              <div className="p-2 space-y-1">
                <AnimatePresence mode="wait">
                  {isSearching ? (
                    <motion.div
                      key="loading"
                      initial={{ opacity: 0 }}
                      animate={{ opacity: 1 }}
                      exit={{ opacity: 0 }}
                    >
                      {Array.from({ length: 5 }).map((_, i) => (
                        <div key={i} className="p-3">
                          <Skeleton className="h-4 w-3/4 mb-2" />
                          <Skeleton className="h-3 w-full mb-1" />
                          <Skeleton className="h-3 w-1/2" />
                        </div>
                      ))}
                    </motion.div>
                  ) : hasSearchResults ? (
                    <motion.div
                      key="search-results"
                      initial={{ opacity: 0 }}
                      animate={{ opacity: 1 }}
                      exit={{ opacity: 0 }}
                      className="space-y-1"
                    >
                      {filteredSearchResults?.map((result) => (
                        <SearchResultItem
                          key={result.id}
                          result={result}
                          isSelected={selectedId === result.id}
                          onClick={() => setSelectedId(result.id)}
                        />
                      ))}
                    </motion.div>
                  ) : listLoading ? (
                    <motion.div
                      key="list-loading"
                      initial={{ opacity: 0 }}
                      animate={{ opacity: 1 }}
                      exit={{ opacity: 0 }}
                    >
                      {Array.from({ length: 5 }).map((_, i) => (
                        <div key={i} className="p-3">
                          <Skeleton className="h-4 w-3/4 mb-2" />
                          <Skeleton className="h-3 w-1/2" />
                        </div>
                      ))}
                    </motion.div>
                  ) : (
                    <motion.div
                      key="documents"
                      initial={{ opacity: 0 }}
                      animate={{ opacity: 1 }}
                      exit={{ opacity: 0 }}
                      className="space-y-1"
                    >
                      {filteredDocs?.map(doc => (
                        <DocumentListItem
                          key={doc.id}
                          doc={doc}
                          isSelected={selectedId === doc.id}
                          onClick={() => setSelectedId(doc.id)}
                        />
                      ))}
                    </motion.div>
                  )}
                </AnimatePresence>
              </div>
            </ScrollArea>

            {/* Only show pagination when browsing documents, not search results */}
            {!hasSearchResults && (
              <div className="p-3 border-t border-border flex items-center justify-between">
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => setPage(p => Math.max(1, p - 1))}
                  disabled={page === 1}
                >
                  <ChevronLeft className="h-4 w-4" />
                </Button>
                <span className="text-xs text-muted-foreground">
                  Page {page} of {totalPages || 1}
                </span>
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => setPage(p => Math.min(totalPages, p + 1))}
                  disabled={page >= totalPages}
                >
                  <ChevronRight className="h-4 w-4" />
                </Button>
              </div>
            )}
          </div>
        </ResizablePanel>

        <ResizableHandle withHandle />

        <ResizablePanel defaultSize={65}>
          <div className="h-full flex flex-col bg-background">
            {selectedDoc ? (
              <>
                <div className="p-4 border-b border-border flex items-center justify-between">
                  <div>
                    <h2 className="font-medium">{selectedDoc.filename}</h2>
                    <p className="text-xs text-muted-foreground">
                      {selectedDoc.wordCount} words • {selectedDoc.source}
                    </p>
                  </div>
                  <AlertDialog>
                    <AlertDialogTrigger asChild>
                      <Button variant="ghost" size="icon" className="text-destructive" aria-label="Delete document">
                        <Trash2 className="h-4 w-4" />
                      </Button>
                    </AlertDialogTrigger>
                    <AlertDialogContent>
                      <AlertDialogHeader>
                        <AlertDialogTitle>Delete document?</AlertDialogTitle>
                        <AlertDialogDescription>
                          This will permanently remove "{selectedDoc.filename}" from your knowledge base.
                        </AlertDialogDescription>
                      </AlertDialogHeader>
                      <AlertDialogFooter>
                        <AlertDialogCancel>Cancel</AlertDialogCancel>
                        <AlertDialogAction onClick={() => deleteMutation.mutate(selectedDoc.id)}>
                          Delete
                        </AlertDialogAction>
                      </AlertDialogFooter>
                    </AlertDialogContent>
                  </AlertDialog>
                </div>

                <div className="px-4 py-2 border-b border-border flex gap-2 flex-wrap">
                  {selectedDoc.topics.map(topic => (
                    <Badge key={topic} variant="outline">{topic}</Badge>
                  ))}
                </div>

                {/* Render based on file type */}
                {selectedDoc.fileType === 'audio' ? (
                  <AudioDocumentViewer document={selectedDoc} />
                ) : selectedDoc.fileType === 'image' && selectedDoc.imageId ? (
                  <ScrollArea className="flex-1">
                    <div className="p-4">
                      <div className="space-y-4">
                        {/* Image display with tabs for Original/Redacted */}
                        <Tabs defaultValue="original" className="w-full">
                          <TabsList className="grid w-full grid-cols-2 max-w-[300px]">
                            <TabsTrigger value="original">Original</TabsTrigger>
                            <TabsTrigger value="redacted" disabled={selectedDoc.redactionPending}>
                              {selectedDoc.redactionPending ? (
                                <span className="flex items-center gap-1">
                                  <Loader2 className="h-3 w-3 animate-spin" />
                                  Processing...
                                </span>
                              ) : (
                                'Redacted'
                              )}
                            </TabsTrigger>
                          </TabsList>
                          <TabsContent value="original" className="mt-3">
                            <div className="relative rounded-lg overflow-hidden border border-border bg-muted/30">
                              <img
                                src={`${VECTOR_STORE_URL}/api/image/serve/${selectedDoc.imageId}?context=user`}
                                alt={selectedDoc.caption || selectedDoc.filename}
                                className="max-w-full h-auto mx-auto"
                                style={{ maxHeight: '60vh' }}
                              />
                            </div>
                          </TabsContent>
                          <TabsContent value="redacted" className="mt-3">
                            <div className="relative rounded-lg overflow-hidden border border-border bg-muted/30">
                              <img
                                src={`${VECTOR_STORE_URL}/api/image/serve/${selectedDoc.imageId}?context=llm`}
                                alt={`Redacted: ${selectedDoc.caption || selectedDoc.filename}`}
                                className="max-w-full h-auto mx-auto"
                                style={{ maxHeight: '60vh' }}
                              />
                              {selectedDoc.hasPii && (
                                <div className="absolute top-2 right-2">
                                  <Badge variant="outline" className="bg-background/80 text-warning gap-1">
                                    <ShieldAlert className="h-3 w-3" />
                                    PII Redacted
                                  </Badge>
                                </div>
                              )}
                            </div>
                          </TabsContent>
                        </Tabs>

                        {/* Image metadata */}
                        <div className="space-y-3">
                          {/* Caption */}
                          {selectedDoc.caption && (
                            <div className="p-3 rounded-lg bg-muted/50 border border-border">
                              <p className="text-xs text-muted-foreground mb-1 font-medium">AI Caption</p>
                              <p className="text-sm">{selectedDoc.caption}</p>
                            </div>
                          )}

                          {/* Image info */}
                          <div className="flex flex-wrap gap-2 text-xs text-muted-foreground">
                            {selectedDoc.width && selectedDoc.height && (
                              <Badge variant="outline">
                                {selectedDoc.width} × {selectedDoc.height}
                              </Badge>
                            )}
                            <Badge variant="outline" className="uppercase">
                              {selectedDoc.extension}
                            </Badge>
                            {/* Only show PII status when redaction is complete */}
                            {selectedDoc.redactionPending ? (
                              <Badge variant="outline" className="text-muted-foreground gap-1">
                                <Loader2 className="h-3 w-3 animate-spin" />
                                Scanning for PII...
                              </Badge>
                            ) : selectedDoc.hasPii ? (
                              <Badge variant="outline" className="text-warning gap-1">
                                <ShieldAlert className="h-3 w-3" />
                                PII Detected
                              </Badge>
                            ) : selectedDoc.redactionComplete ? (
                              <Badge variant="outline" className="text-success gap-1">
                                <Shield className="h-3 w-3" />
                                No PII
                              </Badge>
                            ) : null}
                          </div>

                          {/* PII types found */}
                          {selectedDoc.hasPii && selectedDoc.piiTypesFound && selectedDoc.piiTypesFound.length > 0 && (
                            <div className="flex flex-wrap gap-1">
                              <span className="text-xs text-muted-foreground">Redacted:</span>
                              {selectedDoc.piiTypesFound.map(type => (
                                <Badge key={type} variant="secondary" className="text-xs">
                                  {type}
                                </Badge>
                              ))}
                            </div>
                          )}
                        </div>
                      </div>
                    </div>
                  </ScrollArea>
                ) : (
                  <ScrollArea className="flex-1">
                    <div className="p-4">
                      <DocumentContentViewer doc={selectedDoc} />
                    </div>
                  </ScrollArea>
                )}
              </>
            ) : (
              <div className="h-full flex items-center justify-center text-muted-foreground">
                <div className="text-center">
                  <FileText className="h-12 w-12 mx-auto mb-3 opacity-50" />
                  <p className="text-sm">Select a document to view</p>
                </div>
              </div>
            )}
          </div>
        </ResizablePanel>
      </ResizablePanelGroup>
    </div>
  );
}
