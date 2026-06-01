import { useState, useMemo, useRef, useEffect } from 'react';
import { useQuery } from '@tanstack/react-query';
import { motion, AnimatePresence } from 'framer-motion';
import {
  FolderOpen, FolderPlus, ChevronRight, ChevronDown, FileText, FileCode, FileJson,
  FileAudio, Image as ImageIcon,
  MoreHorizontal, Pencil, Trash2, X, Search, ChevronLeft, FolderMinus,
} from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import {
  ContextMenu, ContextMenuContent, ContextMenuItem, ContextMenuTrigger, ContextMenuSeparator,
} from '@/components/ui/context-menu';
import {
  DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger,
  DropdownMenuSeparator, DropdownMenuSub, DropdownMenuSubTrigger, DropdownMenuSubContent,
} from '@/components/ui/dropdown-menu';
import {
  AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent,
  AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle,
  AlertDialogTrigger,
} from '@/components/ui/alert-dialog';
import { listVectorDocuments } from '@/lib/api';
import { useCanvasStore } from './store/canvasStore';
import type { VectorDocument, Folder } from '@/types';

const fileIcons: Record<string, { icon: typeof FileText; color: string }> = {
  code: { icon: FileCode, color: 'text-blue-500' },
  document: { icon: FileText, color: 'text-red-500' },
  data: { icon: FileJson, color: 'text-green-500' },
  text: { icon: FileText, color: 'text-muted-foreground' },
  audio: { icon: FileAudio, color: 'text-purple-500' },
  image: { icon: ImageIcon, color: 'text-amber-500' },
};

interface FileExplorerProps {
  onSelectDocument: (docId: number) => void;
}

export function FileExplorer({ onSelectDocument }: FileExplorerProps) {
  const [filterQuery, setFilterQuery] = useState('');
  const [collapsedFolders, setCollapsedFolders] = useState<Set<string>>(new Set());
  const [renamingFolderId, setRenamingFolderId] = useState<string | null>(null);
  const [renameValue, setRenameValue] = useState('');
  const [creatingFolder, setCreatingFolder] = useState(false);
  const [newFolderName, setNewFolderName] = useState('');
  const renameInputRef = useRef<HTMLInputElement>(null);
  const newFolderInputRef = useRef<HTMLInputElement>(null);
  const selectedDocRef = useRef<HTMLDivElement>(null);

  const fileExplorerOpen = useCanvasStore((s) => s.fileExplorerOpen);
  const fileExplorerSelectedDocId = useCanvasStore((s) => s.fileExplorerSelectedDocId);
  const folders = useCanvasStore((s) => s.folders);
  const store = useCanvasStore;

  const { data: docData } = useQuery({
    queryKey: ['allDocuments'],
    queryFn: () => listVectorDocuments(1, 500),
  });

  const allDocs = docData?.documents ?? [];

  // Build lookup: docId → document
  const docMap = useMemo(() => {
    const m = new Map<number, VectorDocument>();
    for (const d of allDocs) m.set(d.id, d);
    return m;
  }, [allDocs]);

  // Compute unfiled docs (not in any folder)
  const filedDocIds = useMemo(() => {
    const s = new Set<number>();
    for (const f of folders) for (const id of f.documentIds) s.add(id);
    return s;
  }, [folders]);

  const unfiledDocs = useMemo(
    () => allDocs.filter((d) => !filedDocIds.has(d.id)),
    [allDocs, filedDocIds]
  );

  // Filter
  const lowerFilter = filterQuery.toLowerCase();
  const filterDoc = (d: VectorDocument) =>
    !filterQuery ||
    d.filename.toLowerCase().includes(lowerFilter) ||
    d.primaryTopic?.toLowerCase().includes(lowerFilter);

  // Scroll to selected doc
  useEffect(() => {
    if (fileExplorerSelectedDocId !== null && fileExplorerSelectedDocId !== undefined && selectedDocRef.current) {
      selectedDocRef.current.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    }
  }, [fileExplorerSelectedDocId]);

  // Focus rename/create inputs
  useEffect(() => {
    if (renamingFolderId && renameInputRef.current) renameInputRef.current.focus();
  }, [renamingFolderId]);
  useEffect(() => {
    if (creatingFolder && newFolderInputRef.current) newFolderInputRef.current.focus();
  }, [creatingFolder]);

  const toggleFolder = (id: string) => {
    setCollapsedFolders((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id); else next.add(id);
      return next;
    });
  };

  const handleStartRename = (folder: Folder) => {
    setRenamingFolderId(folder.id);
    setRenameValue(folder.name);
  };

  const handleFinishRename = () => {
    if (renamingFolderId && renameValue.trim()) {
      store.getState().renameFolder(renamingFolderId, renameValue.trim());
    }
    setRenamingFolderId(null);
    setRenameValue('');
  };

  const handleCreateFolder = () => {
    if (newFolderName.trim()) {
      store.getState().createFolder(newFolderName.trim());
      setNewFolderName('');
      setCreatingFolder(false);
    }
  };

  const handleDocClick = (docId: number) => {
    store.getState().setFileExplorerSelectedDocId(docId);
    onSelectDocument(docId);
  };

  const renderDocItem = (doc: VectorDocument) => {
    const { icon: Icon, color } = fileIcons[doc.fileType] || fileIcons.text;
    const isSelected = doc.id === fileExplorerSelectedDocId;

    return (
      <ContextMenu key={doc.id}>
        <ContextMenuTrigger>
          <div
            ref={isSelected ? selectedDocRef : undefined}
            className={`
              flex items-center gap-2 px-2 py-1.5 rounded-md cursor-pointer text-xs
              transition-colors group
              ${isSelected ? 'bg-primary/10 text-primary' : 'hover:bg-accent/50'}
            `}
            onClick={() => handleDocClick(doc.id)}
          >
            <Icon className={`h-3.5 w-3.5 shrink-0 ${color}`} />
            <div className="flex-1 min-w-0">
              <div className="truncate">{doc.filename}</div>
              {doc.primaryTopic && (
                <div className="text-[10px] text-muted-foreground truncate">{doc.primaryTopic}</div>
              )}
            </div>
          </div>
        </ContextMenuTrigger>
        <ContextMenuContent>
          {folders.length > 0 && (
            <>
              {folders.map((f) => {
                const inFolder = f.documentIds.includes(doc.id);
                return (
                  <ContextMenuItem
                    key={f.id}
                    onClick={() => {
                      if (inFolder) {
                        store.getState().removeDocumentFromFolder(f.id, doc.id);
                      } else {
                        store.getState().addDocumentToFolder(f.id, doc.id);
                      }
                    }}
                  >
                    {inFolder ? (
                      <><FolderMinus className="h-3.5 w-3.5 mr-2" /> Remove from {f.name}</>
                    ) : (
                      <><FolderOpen className="h-3.5 w-3.5 mr-2" /> Add to {f.name}</>
                    )}
                  </ContextMenuItem>
                );
              })}
              <ContextMenuSeparator />
            </>
          )}
          <ContextMenuItem onClick={() => handleDocClick(doc.id)}>
            Show on canvas
          </ContextMenuItem>
        </ContextMenuContent>
      </ContextMenu>
    );
  };

  if (!fileExplorerOpen) {
    return (
      <Button
        variant="outline"
        size="icon"
        className="absolute top-24 left-4 z-20 shadow-sm bg-card/95 backdrop-blur-sm"
        onClick={() => store.getState().setFileExplorerOpen(true)}
        aria-label="Open file explorer"
      >
        <ChevronRight className="h-4 w-4" />
      </Button>
    );
  }

  return (
    <AnimatePresence>
      <motion.div
        initial={{ x: -280, opacity: 0 }}
        animate={{ x: 0, opacity: 1 }}
        exit={{ x: -280, opacity: 0 }}
        transition={{ type: 'spring', stiffness: 300, damping: 30 }}
        className="absolute top-24 left-4 w-[280px] max-h-[calc(100vh-16rem)] bg-card/95 backdrop-blur-sm border border-border rounded-lg z-20 shadow-md flex flex-col overflow-hidden"
      >
        {/* Header */}
        <div className="flex items-center justify-between px-3 pt-3 pb-2 flex-shrink-0">
          <span className="text-sm font-medium">Files</span>
          <div className="flex items-center gap-1">
            <Button
              variant="ghost"
              size="icon"
              className="h-6 w-6"
              onClick={() => { setCreatingFolder(true); setNewFolderName(''); }}
              title="New Folder"
              aria-label="New folder"
            >
              <FolderPlus className="h-3.5 w-3.5" />
            </Button>
            <Button
              variant="ghost"
              size="icon"
              className="h-6 w-6"
              onClick={() => store.getState().setFileExplorerOpen(false)}
              aria-label="Close file explorer"
            >
              <ChevronLeft className="h-4 w-4" />
            </Button>
          </div>
        </div>

        {/* Local filter */}
        <div className="px-3 pb-2 flex-shrink-0">
          <div className="relative">
            <Search className="absolute left-2 top-1/2 -translate-y-1/2 h-3 w-3 text-muted-foreground" />
            <Input
              placeholder="Filter files..."
              value={filterQuery}
              onChange={(e) => setFilterQuery(e.target.value)}
              className="h-7 pl-7 pr-7 text-xs"
            />
            {filterQuery && (
              <Button
                variant="ghost"
                size="icon"
                className="absolute right-1 top-1/2 -translate-y-1/2 h-5 w-5"
                onClick={() => setFilterQuery('')}
              >
                <X className="h-3 w-3" />
              </Button>
            )}
          </div>
        </div>

        {/* Scrollable content */}
        <div className="flex-1 min-h-0 overflow-y-auto">
          <div className="px-3 pb-3 space-y-1">
            {/* New folder input */}
            {creatingFolder && (
              <div className="flex items-center gap-1 py-1">
                <FolderOpen className="h-3.5 w-3.5 text-muted-foreground shrink-0" />
                <Input
                  ref={newFolderInputRef}
                  value={newFolderName}
                  onChange={(e) => setNewFolderName(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter') handleCreateFolder();
                    if (e.key === 'Escape') setCreatingFolder(false);
                  }}
                  onBlur={() => {
                    if (newFolderName.trim()) handleCreateFolder();
                    else setCreatingFolder(false);
                  }}
                  placeholder="Folder name..."
                  className="h-6 text-xs flex-1"
                />
              </div>
            )}

            {/* Folders */}
            {folders.map((folder) => {
              const isCollapsed = collapsedFolders.has(folder.id);
              const folderDocs = folder.documentIds
                .map((id) => docMap.get(id))
                .filter((d): d is VectorDocument => d !== null && d !== undefined && filterDoc(d));

              return (
                <div key={folder.id}>
                  <div className="flex items-center gap-1 py-1 group">
                    <button
                      className="flex items-center gap-1.5 flex-1 min-w-0 text-left"
                      onClick={() => toggleFolder(folder.id)}
                    >
                      {isCollapsed ? (
                        <ChevronRight className="h-3 w-3 text-muted-foreground shrink-0" />
                      ) : (
                        <ChevronDown className="h-3 w-3 text-muted-foreground shrink-0" />
                      )}
                      <FolderOpen className="h-3.5 w-3.5 text-amber-500 shrink-0" />
                      {renamingFolderId === folder.id ? (
                        <Input
                          ref={renameInputRef}
                          value={renameValue}
                          onChange={(e) => setRenameValue(e.target.value)}
                          onKeyDown={(e) => {
                            if (e.key === 'Enter') handleFinishRename();
                            if (e.key === 'Escape') setRenamingFolderId(null);
                          }}
                          onBlur={handleFinishRename}
                          className="h-5 text-xs flex-1"
                          onClick={(e) => e.stopPropagation()}
                        />
                      ) : (
                        <span className="text-xs font-medium truncate">{folder.name}</span>
                      )}
                    </button>
                    <span className="text-[10px] text-muted-foreground">{folderDocs.length}</span>
                    <DropdownMenu>
                      <DropdownMenuTrigger asChild>
                        <Button
                          variant="ghost"
                          size="icon"
                          className="h-5 w-5 opacity-0 group-hover:opacity-100 focus:opacity-100 transition-opacity"
                          aria-label="File options"
                        >
                          <MoreHorizontal className="h-3 w-3" />
                        </Button>
                      </DropdownMenuTrigger>
                      <DropdownMenuContent align="start" className="w-40">
                        <DropdownMenuItem onClick={() => handleStartRename(folder)}>
                          <Pencil className="h-3.5 w-3.5 mr-2" /> Rename
                        </DropdownMenuItem>
                        <DropdownMenuSeparator />
                        <AlertDialog>
                          <AlertDialogTrigger asChild>
                            <DropdownMenuItem
                              className="text-destructive"
                              onSelect={(e) => e.preventDefault()}
                            >
                              <Trash2 className="h-3.5 w-3.5 mr-2" /> Delete
                            </DropdownMenuItem>
                          </AlertDialogTrigger>
                          <AlertDialogContent>
                            <AlertDialogHeader>
                              <AlertDialogTitle>Delete folder "{folder.name}"?</AlertDialogTitle>
                              <AlertDialogDescription>
                                This will delete the folder and unfile {folderDocs.length} document{folderDocs.length !== 1 ? 's' : ''}. Documents will not be deleted.
                              </AlertDialogDescription>
                            </AlertDialogHeader>
                            <AlertDialogFooter>
                              <AlertDialogCancel>Cancel</AlertDialogCancel>
                              <AlertDialogAction onClick={() => store.getState().deleteFolder(folder.id)}>
                                Delete folder
                              </AlertDialogAction>
                            </AlertDialogFooter>
                          </AlertDialogContent>
                        </AlertDialog>
                      </DropdownMenuContent>
                    </DropdownMenu>
                  </div>
                  {!isCollapsed && (
                    <div className="pl-5 space-y-0.5">
                      {folderDocs.length > 0 ? (
                        folderDocs.map(renderDocItem)
                      ) : (
                        <p className="text-[10px] text-muted-foreground py-1 pl-2">Empty folder</p>
                      )}
                    </div>
                  )}
                </div>
              );
            })}

            {/* Unfiled documents */}
            {unfiledDocs.filter(filterDoc).length > 0 && (
              <div>
                {folders.length > 0 && (
                  <div className="text-[10px] uppercase tracking-wider text-muted-foreground font-medium pt-2 pb-1">
                    Unfiled
                  </div>
                )}
                <div className="space-y-0.5">
                  {unfiledDocs.filter(filterDoc).map(renderDocItem)}
                </div>
              </div>
            )}

            {allDocs.length === 0 && (
              <p className="text-xs text-muted-foreground text-center py-4">No documents yet</p>
            )}
          </div>
        </div>
      </motion.div>
    </AnimatePresence>
  );
}
