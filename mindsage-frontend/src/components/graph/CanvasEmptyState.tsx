import { Search, Loader2, FileX } from 'lucide-react';

export function CanvasEmptyState() {
  return (
    <div className="absolute inset-0 z-10 flex flex-col items-center justify-center pointer-events-none">
      <div className="p-4 rounded-full bg-muted/60 mb-4">
        <Search className="h-8 w-8 text-muted-foreground" />
      </div>
      <h3 className="text-lg font-medium text-foreground mb-1">Search your knowledge base</h3>
      <p className="text-sm text-muted-foreground max-w-xs text-center">
        Type a query and press Enter to find documents semantically related to your search.
      </p>
    </div>
  );
}

export function CanvasSearchingState() {
  return (
    <div className="absolute inset-0 z-10 flex flex-col items-center justify-center pointer-events-none">
      <Loader2 className="h-8 w-8 text-muted-foreground animate-spin mb-4" />
      <p className="text-sm text-muted-foreground">Searching...</p>
    </div>
  );
}

export function CanvasNoResultsState({ query }: { query: string }) {
  return (
    <div className="absolute inset-0 z-10 flex flex-col items-center justify-center pointer-events-none">
      <div className="p-4 rounded-full bg-muted/60 mb-4">
        <FileX className="h-8 w-8 text-muted-foreground" />
      </div>
      <h3 className="text-lg font-medium text-foreground mb-1">No documents found</h3>
      <p className="text-sm text-muted-foreground max-w-xs text-center">
        No results for &ldquo;{query}&rdquo;. Try a different search term.
      </p>
    </div>
  );
}
