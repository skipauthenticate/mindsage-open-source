import { useEffect, useRef, useState } from 'react';
import type NoVncRFB from '@novnc/novnc';
import { useSearchParams, useNavigate } from 'react-router-dom';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import {
  Monitor,
  Maximize2,
  Minimize2,
  RefreshCw,
  ArrowLeft,
  Loader2,
  Wifi,
  WifiOff,
  Lock,
  Eye,
  EyeOff,
} from 'lucide-react';
import { useQuery } from '@tanstack/react-query';
import { api } from '@/lib/api';

type ConnectionState = 'disconnected' | 'connecting' | 'connected' | 'password' | 'failed';

type RFBInstance = NoVncRFB;

export function VncViewer() {
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();
  const canvasRef = useRef<HTMLDivElement>(null);
  const rfbRef = useRef<RFBInstance | null>(null);

  const [connectionState, setConnectionState] = useState<ConnectionState>('disconnected');
  const [password, setPassword] = useState('');
  const [showPassword, setShowPassword] = useState(false);
  const [isFullscreen, setIsFullscreen] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  // Get server info for default connection
  const { data: serverInfo } = useQuery({
    queryKey: ['serverInfo'],
    queryFn: api.getServerInfo,
    staleTime: 60000,
  });

  // Get VNC status
  const { data: vncStatus } = useQuery({
    queryKey: ['vncStatus'],
    queryFn: api.getVncStatus,
    refetchInterval: connectionState === 'disconnected' ? 5000 : false,
  });

  const host = searchParams.get('host') || serverInfo?.ipAddress || window.location.hostname;
  const port = searchParams.get('port') || vncStatus?.wsPort?.toString() || '6080';
  const wsUrl = `ws://${host}:${port}/websockify`;

  const connect = async (pwd?: string) => {
    if (!canvasRef.current) return;

    // Disconnect existing connection
    if (rfbRef.current) {
      rfbRef.current.disconnect();
      rfbRef.current = null;
    }

    setConnectionState('connecting');
    setErrorMessage(null);

    try {
      // Dynamic import to avoid top-level await issues with noVNC
      const { default: RFB } = await import('@novnc/novnc');

      const rfb = new RFB(canvasRef.current, wsUrl, {
        credentials: { password: pwd || password || '' },
      });

      rfb.scaleViewport = true;
      rfb.resizeSession = true;
      rfb.background = '#0f172a'; // slate-900

      rfb.addEventListener('connect', () => {
        setConnectionState('connected');
        setErrorMessage(null);
      });

      rfb.addEventListener('disconnect', (e: CustomEvent) => {
        const detail = e.detail as { clean?: boolean };
        if (detail.clean) {
          setConnectionState('disconnected');
        } else {
          setConnectionState('failed');
          setErrorMessage('Connection lost unexpectedly');
        }
        rfbRef.current = null;
      });

      rfb.addEventListener('credentialsrequired', () => {
        setConnectionState('password');
      });

      rfb.addEventListener('securityfailure', (e: CustomEvent) => {
        const detail = e.detail as { reason?: string };
        setConnectionState('failed');
        setErrorMessage(detail.reason || 'Authentication failed');
      });

      rfbRef.current = rfb;
    } catch (err) {
      setConnectionState('failed');
      setErrorMessage(String(err));
    }
  };

  const disconnect = () => {
    if (rfbRef.current) {
      rfbRef.current.disconnect();
      rfbRef.current = null;
    }
    setConnectionState('disconnected');
  };

  const handlePasswordSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    connect(password);
  };

  const toggleFullscreen = () => {
    if (!document.fullscreenElement) {
      canvasRef.current?.requestFullscreen();
      setIsFullscreen(true);
    } else {
      document.exitFullscreen();
      setIsFullscreen(false);
    }
  };

  useEffect(() => {
    const handleFullscreenChange = () => {
      setIsFullscreen(!!document.fullscreenElement);
    };
    document.addEventListener('fullscreenchange', handleFullscreenChange);
    return () => {
      document.removeEventListener('fullscreenchange', handleFullscreenChange);
      // Cleanup on unmount
      if (rfbRef.current) {
        rfbRef.current.disconnect();
      }
    };
  }, []);

  // Auto-resize on window resize
  useEffect(() => {
    const handleResize = () => {
      if (rfbRef.current) {
        rfbRef.current.scaleViewport = true;
      }
    };
    window.addEventListener('resize', handleResize);
    return () => window.removeEventListener('resize', handleResize);
  }, []);

  return (
    <div className="min-h-screen bg-gradient-to-b from-slate-900 to-slate-800 flex flex-col">
      {/* Header */}
      <header className="border-b border-slate-700 bg-slate-900/80 backdrop-blur-sm">
        <div className="container mx-auto px-4 py-3 flex items-center justify-between">
          <div className="flex items-center gap-4">
            <Button
              variant="ghost"
              size="sm"
              onClick={() => navigate('/')}
              className="text-slate-300 hover:text-white"
            >
              <ArrowLeft className="h-4 w-4 mr-2" />
              Back to MindSage
            </Button>
            <div className="h-6 w-px bg-slate-700" />
            <div className="flex items-center gap-2">
              <Monitor className="h-5 w-5 text-blue-400" />
              <span className="font-semibold text-white">Browser Remote Access</span>
            </div>
          </div>

          <div className="flex items-center gap-3">
            <Badge
              variant={connectionState === 'connected' ? 'default' : 'secondary'}
              className={connectionState === 'connected' ? 'bg-green-600' : ''}
            >
              {connectionState === 'connected' ? (
                <><Wifi className="h-3 w-3 mr-1" /> Connected</>
              ) : connectionState === 'connecting' ? (
                <><Loader2 className="h-3 w-3 mr-1 animate-spin" /> Connecting</>
              ) : (
                <><WifiOff className="h-3 w-3 mr-1" /> Disconnected</>
              )}
            </Badge>

            {connectionState === 'connected' && (
              <>
                <Button
                  variant="outline"
                  size="sm"
                  onClick={toggleFullscreen}
                  className="border-slate-600 text-slate-300 hover:text-white"
                >
                  {isFullscreen ? (
                    <Minimize2 className="h-4 w-4" />
                  ) : (
                    <Maximize2 className="h-4 w-4" />
                  )}
                </Button>
                <Button
                  variant="outline"
                  size="sm"
                  onClick={disconnect}
                  className="border-slate-600 text-slate-300 hover:text-white"
                >
                  Disconnect
                </Button>
              </>
            )}
          </div>
        </div>
      </header>

      {/* Main content */}
      <main className="flex-1 flex items-center justify-center p-4">
        {connectionState === 'disconnected' || connectionState === 'password' || connectionState === 'failed' ? (
          <Card className="w-full max-w-md bg-slate-800 border-slate-700">
            <CardHeader className="text-center">
              <div className="mx-auto w-16 h-16 rounded-full bg-blue-500/10 flex items-center justify-center mb-4">
                <Monitor className="h-8 w-8 text-blue-400" />
              </div>
              <CardTitle className="text-2xl text-white">
                {connectionState === 'password' ? 'Authentication Required' : 'Connect to Browser'}
              </CardTitle>
              <CardDescription className="text-slate-400">
                {connectionState === 'password'
                  ? 'Enter the VNC password to continue'
                  : 'Access the remote browser session running on your device'
                }
              </CardDescription>
            </CardHeader>
            <CardContent>
              {errorMessage && (
                <div className="mb-4 p-3 rounded-lg bg-red-500/10 border border-red-500/20 text-red-400 text-sm">
                  {errorMessage}
                </div>
              )}

              {!vncStatus?.enabled && connectionState === 'disconnected' && (
                <div className="mb-4 p-3 rounded-lg bg-yellow-500/10 border border-yellow-500/20 text-yellow-400 text-sm">
                  VNC session is not running. Launch the browser with VNC mode enabled from the main UI.
                </div>
              )}

              <form onSubmit={handlePasswordSubmit} className="space-y-4">
                <div>
                  <label className="text-sm text-slate-400 block mb-2">Server</label>
                  <div className="px-3 py-2 rounded-md bg-slate-700/50 border border-slate-600 text-slate-300 font-mono text-sm">
                    {host}:{port}
                  </div>
                </div>

                <div>
                  <label className="text-sm text-slate-400 block mb-2">
                    <Lock className="h-3 w-3 inline mr-1" />
                    Password
                  </label>
                  <div className="relative">
                    <Input
                      type={showPassword ? 'text' : 'password'}
                      value={password}
                      onChange={(e) => setPassword(e.target.value)}
                      placeholder="Enter VNC password"
                      className="bg-slate-700 border-slate-600 text-white pr-10"
                      autoFocus={connectionState === 'password'}
                    />
                    <button
                      type="button"
                      onClick={() => setShowPassword(!showPassword)}
                      className="absolute right-3 top-1/2 -translate-y-1/2 text-slate-400 hover:text-white"
                    >
                      {showPassword ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                    </button>
                  </div>
                  <p className="text-xs text-slate-500 mt-1">Default password: mindsage</p>
                </div>

                <Button
                  type="submit"
                  className="w-full bg-blue-600 hover:bg-blue-700"
                  disabled={connectionState === 'connecting' || (!vncStatus?.enabled && connectionState === 'disconnected')}
                >
                  {connectionState === 'connecting' ? (
                    <><Loader2 className="h-4 w-4 mr-2 animate-spin" /> Connecting...</>
                  ) : (
                    <><RefreshCw className="h-4 w-4 mr-2" /> Connect</>
                  )}
                </Button>
              </form>
            </CardContent>
          </Card>
        ) : null}

        {/* VNC Canvas */}
        <div
          ref={canvasRef}
          className={`bg-slate-900 rounded-lg overflow-hidden ${
            connectionState === 'connected' ? 'w-full h-full' : 'hidden'
          }`}
          style={{
            minHeight: connectionState === 'connected' ? 'calc(100vh - 80px)' : 0,
          }}
        />

        {connectionState === 'connecting' && (
          <div className="absolute inset-0 flex items-center justify-center bg-slate-900/80">
            <div className="text-center">
              <Loader2 className="h-12 w-12 text-blue-400 animate-spin mx-auto mb-4" />
              <p className="text-slate-300">Connecting to remote browser...</p>
            </div>
          </div>
        )}
      </main>
    </div>
  );
}
