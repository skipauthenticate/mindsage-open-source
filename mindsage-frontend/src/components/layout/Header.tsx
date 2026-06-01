import { Link, useLocation } from 'react-router-dom';
import { Brain, Compass, Sun, Moon, Zap, LayoutDashboard } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { useTheme } from '@/components/ThemeProvider';
import { motion } from 'framer-motion';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import { ExtractionStatus } from '@/components/ExtractionStatus';

export function Header() {
  const location = useLocation();
  const { theme, setTheme, resolvedTheme } = useTheme();

  const isActive = (path: string) => location.pathname === path;

  const getThemeIcon = () => {
    switch (resolvedTheme) {
      case 'cyber':
        return <Zap className="h-4 w-4" />;
      case 'light':
        return <Sun className="h-4 w-4" />;
      default:
        return <Moon className="h-4 w-4" />;
    }
  };

  return (
    <motion.header
      initial={{ opacity: 0, y: -10 }}
      animate={{ opacity: 1, y: 0 }}
      className="sticky top-0 z-50 w-full border-b border-border bg-background/95 backdrop-blur supports-[backdrop-filter]:bg-background/60"
    >
      <div className="container flex h-14 items-center justify-between px-4 md:px-6">
        {/* Logo */}
        <Link to="/dashboard" className="flex items-center gap-2 hover:opacity-80 transition-opacity">
          <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-primary">
            <Brain className="h-5 w-5 text-primary-foreground" />
          </div>
          <span className="font-semibold text-lg tracking-tight">MindSage</span>
        </Link>

        {/* Navigation */}
        <nav className="flex items-center gap-1">
          <Link to="/dashboard">
            <Button
              variant={isActive('/dashboard') ? 'secondary' : 'ghost'}
              size="sm"
              className="gap-2"
            >
              <LayoutDashboard className="h-4 w-4" />
              <span className="hidden sm:inline">Dashboard</span>
            </Button>
          </Link>
          <Link to="/explore">
            <Button
              variant={isActive('/explore') ? 'secondary' : 'ghost'}
              size="sm"
              className="gap-2"
            >
              <Compass className="h-4 w-4" />
              <span className="hidden sm:inline">Explore</span>
            </Button>
          </Link>

          {/* Extraction Status Indicator */}
          <ExtractionStatus />

          <div className="mx-2 h-6 w-px bg-border" />

          {/* Theme Dropdown */}
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button variant="ghost" size="icon" className="h-9 w-9" aria-label="Change theme">
                {getThemeIcon()}
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end" className="w-36">
              <DropdownMenuItem 
                onClick={() => setTheme('light')}
                className="gap-2 cursor-pointer"
              >
                <Sun className="h-4 w-4" />
                Light
                {theme === 'light' && <span className="ml-auto text-primary">✓</span>}
              </DropdownMenuItem>
              <DropdownMenuItem 
                onClick={() => setTheme('dark')}
                className="gap-2 cursor-pointer"
              >
                <Moon className="h-4 w-4" />
                Dark
                {theme === 'dark' && <span className="ml-auto text-primary">✓</span>}
              </DropdownMenuItem>
              <DropdownMenuItem 
                onClick={() => setTheme('cyber')}
                className="gap-2 cursor-pointer"
              >
                <Zap className="h-4 w-4" />
                Cyber
                {theme === 'cyber' && <span className="ml-auto text-primary">✓</span>}
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>

        </nav>
      </div>
    </motion.header>
  );
}
