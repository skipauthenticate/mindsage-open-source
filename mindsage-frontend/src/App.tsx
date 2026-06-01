import { lazy, Suspense } from "react";
import { Toaster } from "@/components/ui/toaster";
import { Toaster as Sonner } from "@/components/ui/sonner";
import { TooltipProvider } from "@/components/ui/tooltip";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter, Routes, Route } from "react-router-dom";
import { ThemeProvider } from "@/components/ThemeProvider";
import { ErrorBoundary } from "@/components/ErrorBoundary";
import { Header } from "@/components/layout/Header";
import { DebugPanel } from "@/components/DebugPanel";
import NotFound from "./pages/NotFound";

// Lazy-load heavy pages to reduce initial bundle size
const Index = lazy(() => import("./pages/Index"));
const Explore = lazy(() => import("./pages/Explore"));
const Landing = lazy(() => import("./pages/Landing"));
const VncViewer = lazy(() =>
  import("./pages/VncViewer").then((m) => ({ default: m.VncViewer }))
);

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: 2,
      staleTime: 5_000,
      refetchOnWindowFocus: false,
    },
    mutations: {
      retry: 1,
    },
  },
});

const PageLoader = () => (
  <div className="flex min-h-screen items-center justify-center bg-background">
    <div className="h-8 w-8 animate-spin rounded-full border-4 border-primary border-t-transparent" />
  </div>
);

const App = () => (
  <ErrorBoundary>
    <QueryClientProvider client={queryClient}>
      <ThemeProvider>
        <TooltipProvider>
          <Toaster />
          <Sonner />
          <BrowserRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
            <Suspense fallback={<PageLoader />}>
              <Routes>
                {/* Landing page as default home */}
                <Route path="/" element={<Landing />} />

                {/* VNC Viewer - standalone page without header */}
                <Route path="/vnc" element={<VncViewer />} />

                {/* App routes with header */}
                <Route path="/*" element={
                  <div className="min-h-screen bg-background">
                    <Header />
                    <Routes>
                      <Route path="/dashboard" element={<Index />} />
                      <Route path="/explore" element={<Explore />} />
                      <Route path="*" element={<NotFound />} />
                    </Routes>
                  </div>
                } />
              </Routes>
            </Suspense>
            {import.meta.env.DEV && <DebugPanel />}
          </BrowserRouter>
        </TooltipProvider>
      </ThemeProvider>
    </QueryClientProvider>
  </ErrorBoundary>
);

export default App;
