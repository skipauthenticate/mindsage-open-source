import { useState } from 'react';
import { Bot, Copy, Check, ChevronDown, ExternalLink, Circle } from 'lucide-react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible';
import { useQuery } from '@tanstack/react-query';
import { getMCPStatus, getServerInfo } from '@/lib/api';
import { copyToClipboard } from '@/lib/utils';

export function MCPSetupPanel() {
  const [claudeDesktopOpen, setClaudeDesktopOpen] = useState(false);
  const [claudeCliOpen, setClaudeCliOpen] = useState(false);
  const [copiedUrl, setCopiedUrl] = useState(false);
  const [copiedDesktop, setCopiedDesktop] = useState(false);
  const [copiedCli, setCopiedCli] = useState(false);

  const { data: mcpStatus } = useQuery({
    queryKey: ['mcpStatus'],
    queryFn: getMCPStatus,
  });

  const { data: serverInfo } = useQuery({
    queryKey: ['serverInfo'],
    queryFn: getServerInfo,
  });

  // Dynamic MCP URL based on server IP (fallback to current hostname for network access)
  const serverIp = serverInfo?.ip || window.location.hostname;
  const mcpSseUrl = `http://${serverIp}:8085/sse`;

  const claudeDesktopConfig = `{
  "mcpServers": {
    "mindsage-search": {
      "command": "npx",
      "args": [
        "-y",
        "mcp-remote",
        "${mcpSseUrl}",
        "--transport",
        "sse-only",
        "--allow-http"
      ]
    }
  }
}`;

  const claudeCliCommand = `claude mcp add mindsage-search --transport sse-only ${mcpSseUrl}`;

  const handleCopy = async (text: string, setter: (value: boolean) => void) => {
    await copyToClipboard(text);
    setter(true);
    setTimeout(() => setter(false), 2000);
  };

  return (
    <Card className="h-full">
      <CardHeader className="pb-2">
        <CardTitle className="text-base font-medium flex items-center gap-2">
          <Bot className="h-4 w-4" />
          MCP Integration
        </CardTitle>
        <p className="text-xs text-muted-foreground mt-1">
          Connect Claude Desktop or CLI to search your knowledge base
        </p>
      </CardHeader>
      <CardContent className="pt-0 space-y-4">
        {/* Status */}
        <div className="flex items-center justify-between">
          <Badge 
            variant={mcpStatus?.ready ? 'default' : 'secondary'}
            className="gap-1.5"
          >
            <Circle className={`h-2 w-2 ${mcpStatus?.ready ? 'fill-success text-success' : 'fill-muted-foreground'}`} />
            {mcpStatus?.ready ? 'MCP Ready' : 'Offline'}
          </Badge>
          <span className="text-xs text-muted-foreground">
            {mcpStatus?.documentCount || 0} documents indexed
          </span>
        </div>

        {/* MCP URL */}
        <div className="flex items-center gap-2">
          <code className="flex-1 text-xs bg-muted px-2 py-1.5 rounded truncate">
            {mcpSseUrl}
          </code>
          <Button
            variant="ghost"
            size="icon"
            className="h-7 w-7 shrink-0"
            onClick={() => handleCopy(mcpSseUrl, setCopiedUrl)}
          >
            {copiedUrl ? <Check className="h-3.5 w-3.5" /> : <Copy className="h-3.5 w-3.5" />}
          </Button>
        </div>

        {/* Claude Desktop Setup */}
        <Collapsible open={claudeDesktopOpen} onOpenChange={setClaudeDesktopOpen}>
          <CollapsibleTrigger asChild>
            <Button variant="ghost" size="sm" className="w-full justify-between px-0">
              <span className="text-sm font-medium">Claude Desktop Setup</span>
              <ChevronDown className={`h-4 w-4 transition-transform ${claudeDesktopOpen ? 'rotate-180' : ''}`} />
            </Button>
          </CollapsibleTrigger>
          <CollapsibleContent className="pt-2 space-y-2">
            <p className="text-xs text-muted-foreground">
              Add this to your Claude Desktop config file:
            </p>
            <div className="relative">
              <pre className="text-xs bg-muted p-3 rounded-lg overflow-x-auto custom-scrollbar">
                <code>{claudeDesktopConfig}</code>
              </pre>
              <Button
                variant="ghost"
                size="icon"
                className="absolute top-2 right-2 h-6 w-6"
                onClick={() => handleCopy(claudeDesktopConfig, setCopiedDesktop)}
              >
                {copiedDesktop ? <Check className="h-3 w-3" /> : <Copy className="h-3 w-3" />}
              </Button>
            </div>
          </CollapsibleContent>
        </Collapsible>

        {/* Claude CLI Setup */}
        <Collapsible open={claudeCliOpen} onOpenChange={setClaudeCliOpen}>
          <CollapsibleTrigger asChild>
            <Button variant="ghost" size="sm" className="w-full justify-between px-0">
              <span className="text-sm font-medium">Claude CLI Setup</span>
              <ChevronDown className={`h-4 w-4 transition-transform ${claudeCliOpen ? 'rotate-180' : ''}`} />
            </Button>
          </CollapsibleTrigger>
          <CollapsibleContent className="pt-2 space-y-2">
            <p className="text-xs text-muted-foreground">
              Run this command to add MindSage to Claude CLI:
            </p>
            <div className="relative">
              <pre className="text-xs bg-muted p-3 pr-10 rounded-lg overflow-x-auto">
                <code>{claudeCliCommand}</code>
              </pre>
              <Button
                variant="ghost"
                size="icon"
                className="absolute top-2 right-2 h-6 w-6 bg-muted"
                onClick={() => handleCopy(claudeCliCommand, setCopiedCli)}
              >
                {copiedCli ? <Check className="h-3 w-3" /> : <Copy className="h-3 w-3" />}
              </Button>
            </div>
          </CollapsibleContent>
        </Collapsible>

        <Button variant="link" size="sm" className="h-auto p-0 text-xs" asChild>
          <a href="https://docs.anthropic.com/mcp" target="_blank" rel="noopener noreferrer">
            View MCP Documentation
            <ExternalLink className="h-3 w-3 ml-1" />
          </a>
        </Button>
      </CardContent>
    </Card>
  );
}
