import { useState, useCallback, useEffect } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  Send,
  Upload,
  Smartphone,
  Circle,
  ChevronDown,
  Apple,
  Monitor,
  FileUp,
  CheckCircle,
  Loader2,
  Mic,
  Image as ImageIcon
} from 'lucide-react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { Badge } from '@/components/ui/badge';
import { Progress } from '@/components/ui/progress';
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible';
import { useToast } from '@/hooks/use-toast';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { getLocalSendStatus, startLocalSend, stopLocalSend, uploadFiles, getServerInfo, api } from '@/lib/api';
import { QRCodeSVG } from 'qrcode.react';

export function FileTransferPanel() {
  const [isSetupOpen, setIsSetupOpen] = useState(false);
  const [uploadProgress, setUploadProgress] = useState(0);
  const [isDragging, setIsDragging] = useState(false);
  const [indexingInProgress, setIndexingInProgress] = useState(false);
  const { toast } = useToast();
  const queryClient = useQueryClient();

  const { data: localSendStatus, refetch } = useQuery({
    queryKey: ['localSendStatus'],
    queryFn: getLocalSendStatus,
  });

  const { data: serverInfo } = useQuery({
    queryKey: ['serverInfo'],
    queryFn: getServerInfo,
  });

  const { data: mediaStatus } = useQuery({
    queryKey: ['mediaStatus'],
    queryFn: () => api.getMediaStatus(),
    staleTime: 60000,
  });

  const hasAudio = mediaStatus?.audio?.available ?? false;
  const hasImage = mediaStatus?.image?.available ?? false;

  const toggleMutation = useMutation({
    mutationFn: async () => {
      if (localSendStatus?.running) {
        await stopLocalSend();
      } else {
        await startLocalSend();
      }
    },
    onSuccess: () => {
      refetch();
      toast({
        title: localSendStatus?.running ? 'LocalSend stopped' : 'LocalSend started',
        description: localSendStatus?.running 
          ? 'File transfers are now disabled' 
          : 'Ready to receive files',
      });
    },
  });

  const uploadMutation = useMutation({
    mutationFn: (files: FileList) => uploadFiles(files, setUploadProgress),
    onSuccess: () => {
      setUploadProgress(0);
      setIndexingInProgress(true);
      toast({
        title: 'Upload complete',
        description: 'Indexing files in the background...',
      });
    },
    onError: () => {
      setUploadProgress(0);
      toast({
        variant: 'destructive',
        title: 'Upload failed',
        description: 'There was an error uploading your files',
      });
    },
  });

  // Poll indexing status when files are being indexed
  useEffect(() => {
    if (!indexingInProgress) return;

    let failureCount = 0;
    const MAX_FAILURES = 5;

    const checkIndexingStatus = async () => {
      try {
        const status = await api.getIndexingStatus();
        failureCount = 0; // Reset on success
        if (status.processing === 0 && status.queued === 0) {
          setIndexingInProgress(false);
          toast({
            title: 'Indexing complete',
            description: 'Files have been indexed successfully',
          });
          // Refresh document list
          queryClient.invalidateQueries({ queryKey: ['documents'] });
        }
      } catch {
        failureCount++;
        if (failureCount >= MAX_FAILURES) {
          setIndexingInProgress(false);
          toast({
            variant: 'destructive',
            title: 'Indexing status unavailable',
            description: 'Could not check indexing progress. Your files may still be processing.',
          });
        }
      }
    };

    const interval = setInterval(checkIndexingStatus, 2000);
    // Check immediately
    checkIndexingStatus();

    return () => clearInterval(interval);
  }, [indexingInProgress, toast, queryClient]);

  const handleDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(false);
    if (e.dataTransfer.files.length > 0) {
      uploadMutation.mutate(e.dataTransfer.files);
    }
  }, [uploadMutation]);

  const handleFileSelect = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files.length > 0) {
      uploadMutation.mutate(e.target.files);
    }
  }, [uploadMutation]);

  // Use server IP, fallback to current hostname for network access
  const serverIp = serverInfo?.ip || window.location.hostname;
  const serverPort = serverInfo?.port || 3003;
  const uploadUrl = `http://${serverIp}:${serverPort}/api/files/upload`;

  return (
    <Card className="h-full">
      <CardHeader className="pb-2">
        <CardTitle className="text-base font-medium flex items-center gap-2">
          <FileUp className="h-4 w-4" />
          File Transfer
          {(hasAudio || hasImage) && (
            <span className="flex gap-1 ml-auto">
              {hasAudio && <Badge variant="secondary" className="text-[10px] px-1.5 py-0 gap-0.5"><Mic className="h-2.5 w-2.5" />Audio</Badge>}
              {hasImage && <Badge variant="secondary" className="text-[10px] px-1.5 py-0 gap-0.5"><ImageIcon className="h-2.5 w-2.5" />Image</Badge>}
            </span>
          )}
        </CardTitle>
        <p className="text-xs text-muted-foreground mt-1">
          Upload files{hasAudio || hasImage ? ', audio, or images' : ''} to your searchable knowledge base
        </p>
      </CardHeader>
      <CardContent className="pt-0">
        <Tabs defaultValue="http" className="w-full">
          <TabsList className="grid w-full grid-cols-3 mb-4">
            <TabsTrigger value="localsend" className="text-xs">LocalSend</TabsTrigger>
            <TabsTrigger value="http" className="text-xs">HTTP Upload</TabsTrigger>
            <TabsTrigger value="mobile" className="text-xs">Mobile</TabsTrigger>
          </TabsList>

          <TabsContent value="localsend" className="space-y-4">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                <Circle 
                  className={`h-2.5 w-2.5 ${localSendStatus?.running ? 'fill-success text-success' : 'fill-muted-foreground text-muted-foreground'}`} 
                />
                <span className="text-sm font-medium">{localSendStatus?.deviceName || 'Device'}</span>
              </div>
              <Button
                variant="outline"
                size="sm"
                onClick={() => toggleMutation.mutate()}
                disabled={toggleMutation.isPending}
              >
                {toggleMutation.isPending ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : localSendStatus?.running ? 'Stop' : 'Start'}
              </Button>
            </div>

            <Collapsible open={isSetupOpen} onOpenChange={setIsSetupOpen}>
              <CollapsibleTrigger asChild>
                <Button variant="ghost" size="sm" className="w-full justify-between">
                  <span className="text-xs text-muted-foreground">Download LocalSend</span>
                  <ChevronDown className={`h-4 w-4 transition-transform ${isSetupOpen ? 'rotate-180' : ''}`} />
                </Button>
              </CollapsibleTrigger>
              <CollapsibleContent className="pt-2">
                <div className="grid grid-cols-2 gap-2">
                  <Button variant="outline" size="sm" className="justify-start gap-2" asChild>
                    <a href="https://apps.apple.com/app/localsend" target="_blank" rel="noopener noreferrer">
                      <Apple className="h-4 w-4" />
                      <span className="text-xs">iOS</span>
                    </a>
                  </Button>
                  <Button variant="outline" size="sm" className="justify-start gap-2" asChild>
                    <a href="https://play.google.com/store/apps/details?id=org.localsend.localsend_app" target="_blank" rel="noopener noreferrer">
                      <Smartphone className="h-4 w-4" />
                      <span className="text-xs">Android</span>
                    </a>
                  </Button>
                  <Button variant="outline" size="sm" className="justify-start gap-2 col-span-2" asChild>
                    <a href="https://localsend.org/#/download" target="_blank" rel="noopener noreferrer">
                      <Monitor className="h-4 w-4" />
                      <span className="text-xs">Desktop</span>
                    </a>
                  </Button>
                </div>
              </CollapsibleContent>
            </Collapsible>

            <p className="text-xs text-muted-foreground">
              Send files directly from any device on your local network.
            </p>
          </TabsContent>

          <TabsContent value="http" className="space-y-4">
            <div
              onDragOver={(e) => { e.preventDefault(); setIsDragging(true); }}
              onDragLeave={() => setIsDragging(false)}
              onDrop={handleDrop}
              className={`
                relative flex flex-col items-center justify-center 
                h-32 rounded-lg border-2 border-dashed 
                transition-colors cursor-pointer
                ${isDragging ? 'border-foreground bg-accent' : 'border-border hover:border-muted-foreground'}
              `}
            >
              <input
                type="file"
                multiple
                onChange={handleFileSelect}
                className="absolute inset-0 w-full h-full opacity-0 cursor-pointer"
              />
              <AnimatePresence mode="wait">
                {uploadMutation.isPending ? (
                  <motion.div
                    key="uploading"
                    initial={{ opacity: 0 }}
                    animate={{ opacity: 1 }}
                    exit={{ opacity: 0 }}
                    className="flex flex-col items-center gap-2 w-full px-6"
                  >
                    <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
                    <Progress value={uploadProgress} className="h-1.5" />
                    <span className="text-xs text-muted-foreground">{uploadProgress}%</span>
                  </motion.div>
                ) : indexingInProgress ? (
                  <motion.div
                    key="indexing"
                    initial={{ opacity: 0 }}
                    animate={{ opacity: 1 }}
                    exit={{ opacity: 0 }}
                    className="flex flex-col items-center gap-2"
                  >
                    <Loader2 className="h-6 w-6 animate-spin text-primary" />
                    <span className="text-xs text-muted-foreground text-center">
                      Indexing files...
                    </span>
                  </motion.div>
                ) : (
                  <motion.div
                    key="idle"
                    initial={{ opacity: 0 }}
                    animate={{ opacity: 1 }}
                    exit={{ opacity: 0 }}
                    className="flex flex-col items-center gap-2"
                  >
                    <Upload className="h-6 w-6 text-muted-foreground" />
                    <span className="text-xs text-muted-foreground text-center">
                      Drop files here or click to browse
                    </span>
                    <span className="text-[10px] text-muted-foreground/60 text-center">
                      PDF, TXT, MD, DOCX, CSV{hasAudio ? ', MP3, WAV, M4A' : ''}{hasImage ? ', JPG, PNG' : ''}
                    </span>
                  </motion.div>
                )}
              </AnimatePresence>
            </div>
          </TabsContent>

          <TabsContent value="mobile" className="space-y-4">
            <div className="flex flex-col items-center gap-4">
              <div className="p-3 bg-white rounded-lg">
                <QRCodeSVG value={uploadUrl} size={120} />
              </div>
              <p className="text-xs text-muted-foreground text-center">
                Scan to upload from mobile
              </p>
              <code className="text-xs bg-muted px-2 py-1 rounded break-all">
                {uploadUrl}
              </code>
            </div>
          </TabsContent>
        </Tabs>
      </CardContent>
    </Card>
  );
}
