import { motion } from 'framer-motion';
import { Link } from 'react-router-dom';
import { 
  Brain, 
  Shield, 
  Zap, 
  Lock, 
  Search, 
  GitBranch, 
  Database,
  Terminal,
  ArrowRight,
  Sparkles,
  Network,
  FileText,
  Menu,
  X,
  Download,
  Bot,
  SlidersHorizontal,
  Clock,
  Users,
  Eye
} from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';

import { useState, useEffect } from 'react';

const fadeInUp = {
  initial: { opacity: 0, y: 20 },
  animate: { opacity: 1, y: 0 },
  transition: { duration: 0.5 }
};

function useTypewriter(text: string, delay: number, speed = 40) {
  const [displayed, setDisplayed] = useState('');
  const [done, setDone] = useState(false);

  useEffect(() => {
    const timeout = setTimeout(() => {
      let i = 0;
      const interval = setInterval(() => {
        setDisplayed(text.slice(0, i + 1));
        i++;
        if (i >= text.length) {
          clearInterval(interval);
          setDone(true);
        }
      }, speed);
      return () => clearInterval(interval);
    }, delay);
    return () => clearTimeout(timeout);
  }, [text, delay, speed]);

  return { displayed, done };
}

const staggerContainer = {
  animate: {
    transition: {
      staggerChildren: 0.1
    }
  }
};

function FeatureCard({ 
  icon: Icon, 
  title, 
  description 
}: { 
  icon: React.ElementType; 
  title: string; 
  description: string;
}) {
  return (
    <motion.div
      variants={fadeInUp}
      className="group relative p-6 rounded-xl border border-border bg-card/50 hover:bg-card hover:border-primary/50 transition-all duration-300"
    >
      <div className="absolute inset-0 rounded-xl bg-gradient-to-br from-primary/5 to-transparent opacity-0 group-hover:opacity-100 transition-opacity" />
      <div className="relative">
        <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-primary/10 text-primary mb-4">
          <Icon className="h-5 w-5" />
        </div>
        <h3 className="font-semibold text-lg mb-2">{title}</h3>
        <p className="text-sm text-muted-foreground leading-relaxed">{description}</p>
      </div>
    </motion.div>
  );
}

function StatCard({ value, label }: { value: string; label: string }) {
  return (
    <motion.div variants={fadeInUp} className="text-center">
      <div className="text-4xl font-bold text-primary mb-1">{value}</div>
      <div className="text-sm text-muted-foreground">{label}</div>
    </motion.div>
  );
}

function MobileNav() {
  const [open, setOpen] = useState(false);

  return (
    <div className="sm:hidden">
      <Button variant="ghost" size="icon" aria-label="Toggle menu" onClick={() => setOpen(!open)}>
        {open ? <X className="h-5 w-5" /> : <Menu className="h-5 w-5" />}
      </Button>
      {open && (
        <motion.div
          initial={{ opacity: 0, y: -4 }}
          animate={{ opacity: 1, y: 0 }}
          className="absolute top-16 left-0 right-0 border-b border-border bg-background/95 backdrop-blur-xl p-4 flex flex-col gap-2"
        >
          <Link to="/dashboard" onClick={() => setOpen(false)}>
            <Button variant="ghost" size="sm" className="w-full justify-start">Dashboard</Button>
          </Link>
          <Link to="/explore" onClick={() => setOpen(false)}>
            <Button variant="ghost" size="sm" className="w-full justify-start">Explore</Button>
          </Link>
          <a href="#get-started" onClick={() => setOpen(false)}>
            <Button size="sm" className="w-full gap-2">
              Get Started
              <ArrowRight className="h-3.5 w-3.5" />
            </Button>
          </a>
        </motion.div>
      )}
    </div>
  );
}

const terminalResults = [
  { score: '98%', scoreClass: 'text-success', file: 'attention-is-all-you-need.pdf', tag: 'AI' },
  { score: '94%', scoreClass: 'text-success', file: 'neural-network-notes.md', tag: 'Notes' },
  { score: '87%', scoreClass: 'text-warning', file: 'ml-course-chapter-5.pdf', tag: 'Education' },
];

function TerminalAnimation() {
  const command = 'mindsage search "machine learning papers"';
  const { displayed: typedCommand, done: commandDone } = useTypewriter(command, 800, 35);
  const [showSearching, setShowSearching] = useState(false);
  const [visibleResults, setVisibleResults] = useState(0);

  useEffect(() => {
    if (!commandDone) return;
    const t = setTimeout(() => setShowSearching(true), 300);
    return () => clearTimeout(t);
  }, [commandDone]);

  useEffect(() => {
    if (!showSearching) return;
    let i = 0;
    const interval = setInterval(() => {
      i++;
      setVisibleResults(i);
      if (i >= terminalResults.length) clearInterval(interval);
    }, 400);
    return () => clearInterval(interval);
  }, [showSearching]);

  return (
    <div className="p-6 font-mono text-sm">
      <div className="text-muted-foreground mb-2">
        <span className="text-primary">❯</span> {typedCommand}
        {!commandDone && <span className="animate-pulse">▌</span>}
      </div>
      {showSearching && (
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          className="text-muted-foreground/80 mb-4"
        >
          Searching 1,247 documents...
        </motion.div>
      )}
      <div className="space-y-2 text-muted-foreground/80">
        {terminalResults.slice(0, visibleResults).map((r, i) => (
          <motion.div
            key={i}
            initial={{ opacity: 0, x: -8 }}
            animate={{ opacity: 1, x: 0 }}
            transition={{ duration: 0.3 }}
            className="flex items-center gap-3"
          >
            <span className={`${r.scoreClass} font-semibold`}>{r.score}</span>
            <span>{r.file}</span>
            <Badge variant="secondary" className="text-[10px] px-1.5 py-0">{r.tag}</Badge>
          </motion.div>
        ))}
      </div>
      {visibleResults >= terminalResults.length && (
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          transition={{ delay: 0.3 }}
          className="mt-4 text-muted-foreground"
        >
          <span className="text-primary">❯</span> <span className="animate-pulse">▌</span>
        </motion.div>
      )}
    </div>
  );
}

export default function Landing() {
  return (
    <div className="min-h-screen bg-background text-foreground overflow-hidden">
      {/* Navigation */}
      <motion.nav
        initial={{ opacity: 0, y: -10 }}
        animate={{ opacity: 1, y: 0 }}
        className="fixed top-0 left-0 right-0 z-50 border-b border-border bg-background/80 backdrop-blur-xl"
      >
        <div className="container mx-auto px-6 h-16 flex items-center justify-between">
          <Link to="/" className="flex items-center gap-2.5">
            <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-primary">
              <Brain className="h-5 w-5 text-primary-foreground" />
            </div>
            <span className="font-semibold text-lg tracking-tight">MindSage</span>
          </Link>
          
          {/* Desktop nav */}
          <div className="hidden sm:flex items-center gap-4">
            <Link to="/dashboard">
              <Button variant="ghost" size="sm">Dashboard</Button>
            </Link>
            <Link to="/explore">
              <Button variant="ghost" size="sm">Explore</Button>
            </Link>
            <a href="#get-started">
              <Button size="sm" className="gap-2">
                Get Started
                <ArrowRight className="h-3.5 w-3.5" />
              </Button>
            </a>
          </div>

          {/* Mobile nav toggle */}
          <MobileNav />
        </div>
      </motion.nav>

      {/* Hero Section */}
      <section className="relative pt-32 pb-20 px-6">
        {/* Background gradient */}
        <div className="absolute inset-0 bg-gradient-to-b from-primary/5 via-transparent to-transparent pointer-events-none" />
        
        {/* Grid pattern */}
        <div 
          className="absolute inset-0 opacity-[0.03]"
          style={{
            backgroundImage: `linear-gradient(hsl(var(--border)) 1px, transparent 1px), linear-gradient(90deg, hsl(var(--border)) 1px, transparent 1px)`,
            backgroundSize: '64px 64px'
          }}
        />
        
        <div className="container mx-auto max-w-5xl relative">
          <motion.div
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.6 }}
            viewport={{ once: true }}
            className="text-center"
          >
            <Badge 
              variant="outline" 
              className="mb-6 px-4 py-1.5 border-primary/30 bg-primary/5 text-primary"
            >
              <Sparkles className="h-3.5 w-3.5 mr-2" />
              Privacy-First Knowledge Management
            </Badge>
            
            <h1 className="text-5xl md:text-7xl font-bold tracking-tight mb-6 leading-[1.1]">
              Index everything.
              <br />
              <span className="text-primary">Expose nothing.</span>
            </h1>
            
            <p className="text-lg md:text-xl text-muted-foreground max-w-2xl mx-auto mb-10 leading-relaxed">
              Index, search, and explore your personal knowledge graph with AI. 
              All data stays on your machine—no cloud, no tracking, full control.
            </p>
            
            <div className="flex flex-col sm:flex-row items-center justify-center gap-4">
              <Link to="/dashboard">
                <Button size="lg" className="gap-2 h-12 px-8 text-base">
                  <Terminal className="h-4 w-4" />
                  Launch Dashboard
                </Button>
              </Link>
              <a href="https://github.com/nicholasgriffintn/mindsage" target="_blank" rel="noopener noreferrer">
                <Button size="lg" variant="outline" className="gap-2 h-12 px-8 text-base">
                  <GitBranch className="h-4 w-4" />
                  View on GitHub
                </Button>
              </a>
            </div>
          </motion.div>
          
          {/* Terminal Preview */}
          <motion.div
            initial={{ opacity: 0, y: 40 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.8, delay: 0.3 }}
            className="mt-16 mx-auto max-w-3xl"
          >
            <div className="rounded-xl border border-border bg-card/50 backdrop-blur overflow-hidden shadow-2xl">
              {/* Terminal header */}
              <div className="flex items-center gap-2 px-4 py-3 border-b border-border bg-muted/30">
                <div className="flex gap-1.5">
                  <div className="h-3 w-3 rounded-full bg-destructive/80" />
                  <div className="h-3 w-3 rounded-full bg-warning/80" />
                  <div className="h-3 w-3 rounded-full bg-success/80" />
                </div>
                <span className="text-xs text-muted-foreground ml-2 font-mono">mindsage — zsh</span>
              </div>
              
              {/* Terminal content */}
              <TerminalAnimation />
            </div>
          </motion.div>
        </div>
      </section>

      {/* Stats Section */}
      <section className="py-16 px-6 border-y border-border">
        <motion.div
          variants={staggerContainer}
          initial="initial"
          whileInView="animate"
          viewport={{ once: true }}
          className="container mx-auto max-w-4xl"
        >
          <div className="grid grid-cols-2 md:grid-cols-4 gap-8">
            <StatCard value="100%" label="Local Processing" />
            <StatCard value="<50ms" label="Avg. Search Speed" />
            <StatCard value="10k+" label="Documents Supported" />
            <StatCard value="Zero" label="Cloud Dependencies" />
          </div>
        </motion.div>
      </section>

      {/* Features Grid */}
      <section className="py-24 px-6">
        <div className="container mx-auto max-w-6xl">
          <motion.div
            initial={{ opacity: 0, y: 20 }}
            whileInView={{ opacity: 1, y: 0 }}
            viewport={{ once: true }}
            className="text-center mb-16"
          >
            <Badge variant="outline" className="mb-4">
              Features
            </Badge>
            <h2 className="text-3xl md:text-4xl font-bold mb-4">
              Everything you need for
              <br />
              <span className="text-primary">knowledge management</span>
            </h2>
            <p className="text-muted-foreground max-w-xl mx-auto">
              Powerful tools to capture, organize, and retrieve your personal knowledge—all running locally.
            </p>
          </motion.div>
          
          <motion.div
            variants={staggerContainer}
            initial="initial"
            whileInView="animate"
            viewport={{ once: true }}
            className="grid md:grid-cols-2 lg:grid-cols-3 gap-6"
          >
            <FeatureCard
              icon={Search}
              title="Semantic Search"
              description="Find documents by meaning, not just keywords. AI-powered search understands context and intent."
            />
            <FeatureCard
              icon={Network}
              title="Knowledge Graph"
              description="Visualize connections between ideas, people, and topics in an interactive graph view."
            />
            <FeatureCard
              icon={Database}
              title="Multi-Source Indexing"
              description="Import from ChatGPT, Claude, Notion, Facebook, and local files automatically."
            />
            <FeatureCard
              icon={Lock}
              title="Privacy First"
              description="All processing happens locally. Your data never leaves your machine."
            />
            <FeatureCard
              icon={Zap}
              title="Lightning Fast"
              description="Instant search across thousands of documents with local vector embeddings."
            />
            <FeatureCard
              icon={FileText}
              title="Rich Previews"
              description="View code, markdown, and documents with syntax highlighting and formatting."
            />
          </motion.div>
        </div>
      </section>

      {/* Privacy Superpowers */}
      <section className="py-24 px-6 border-y border-border bg-gradient-to-b from-transparent via-primary/5 to-transparent">
        <div className="container mx-auto max-w-6xl">
          <motion.div
            initial={{ opacity: 0, y: 20 }}
            whileInView={{ opacity: 1, y: 0 }}
            viewport={{ once: true }}
            className="text-center mb-16"
          >
            <Badge variant="outline" className="mb-4 border-primary/30 bg-primary/5 text-primary">
              <Shield className="h-3.5 w-3.5 mr-2" />
              Privacy Superpowers
            </Badge>
            <h2 className="text-3xl md:text-4xl font-bold mb-4">
              Your data, your rules.
              <br />
              <span className="text-primary">No exceptions.</span>
            </h2>
            <p className="text-muted-foreground max-w-2xl mx-auto">
              Take back control from Big Tech. Use powerful AI without sacrificing privacy.
            </p>
          </motion.div>
          
          <motion.div
            variants={staggerContainer}
            initial="initial"
            whileInView="animate"
            viewport={{ once: true }}
            className="grid md:grid-cols-3 gap-8"
          >
            {/* Data Liberation */}
            <motion.div
              variants={fadeInUp}
              className="relative p-8 rounded-2xl border border-border bg-card/50 hover:border-primary/50 transition-all duration-300 group"
            >
              <div className="absolute inset-0 rounded-2xl bg-gradient-to-br from-primary/10 to-transparent opacity-0 group-hover:opacity-100 transition-opacity" />
              <div className="relative">
                <div className="flex h-14 w-14 items-center justify-center rounded-xl bg-primary/10 text-primary mb-6">
                  <Download className="h-7 w-7" />
                </div>
                <h3 className="font-bold text-xl mb-3">Data Liberation Service</h3>
                <p className="text-muted-foreground mb-4 leading-relaxed">
                  Break free from Big Tech. Import your data from Google, Meta, Amazon, and other platforms directly into MindSage on your device.
                </p>
                <div className="space-y-2 text-sm text-muted-foreground">
                  <div className="flex items-center gap-2">
                    <div className="h-1.5 w-1.5 rounded-full bg-primary" />
                    <span>Google Takeout integration</span>
                  </div>
                  <div className="flex items-center gap-2">
                    <div className="h-1.5 w-1.5 rounded-full bg-primary" />
                    <span>Meta data export support</span>
                  </div>
                  <div className="flex items-center gap-2">
                    <div className="h-1.5 w-1.5 rounded-full bg-primary" />
                    <span>Amazon data archives</span>
                  </div>
                </div>
              </div>
            </motion.div>
            
            {/* AI Without Exposure */}
            <motion.div
              variants={fadeInUp}
              className="relative p-8 rounded-2xl border border-border bg-card/50 hover:border-primary/50 transition-all duration-300 group"
            >
              <div className="absolute inset-0 rounded-2xl bg-gradient-to-br from-primary/10 to-transparent opacity-0 group-hover:opacity-100 transition-opacity" />
              <div className="relative">
                <div className="flex h-14 w-14 items-center justify-center rounded-xl bg-primary/10 text-primary mb-6">
                  <Bot className="h-7 w-7" />
                </div>
                <h3 className="font-bold text-xl mb-3">AI Without PII Exposure</h3>
                <p className="text-muted-foreground mb-4 leading-relaxed">
                  Use ChatGPT, Claude, or any LLM provider without your personal data ever leaving your device. Switch providers anytime.
                </p>
                <div className="space-y-2 text-sm text-muted-foreground">
                  <div className="flex items-center gap-2">
                    <div className="h-1.5 w-1.5 rounded-full bg-primary" />
                    <span>Local PII stripping</span>
                  </div>
                  <div className="flex items-center gap-2">
                    <div className="h-1.5 w-1.5 rounded-full bg-primary" />
                    <span>Bring your own API key</span>
                  </div>
                  <div className="flex items-center gap-2">
                    <div className="h-1.5 w-1.5 rounded-full bg-primary" />
                    <span>Hot-swap between providers</span>
                  </div>
                </div>
              </div>
            </motion.div>
            
            {/* Granular Control */}
            <motion.div
              variants={fadeInUp}
              className="relative p-8 rounded-2xl border border-border bg-card/50 hover:border-primary/50 transition-all duration-300 group"
            >
              <div className="absolute inset-0 rounded-2xl bg-gradient-to-br from-primary/10 to-transparent opacity-0 group-hover:opacity-100 transition-opacity" />
              <div className="relative">
                <div className="flex h-14 w-14 items-center justify-center rounded-xl bg-primary/10 text-primary mb-6">
                  <SlidersHorizontal className="h-7 w-7" />
                </div>
                <h3 className="font-bold text-xl mb-3">Granular Data Control</h3>
                <p className="text-muted-foreground mb-4 leading-relaxed">
                  Define exactly what data is shared, with whom, and for how long. Set expiration dates on shared access.
                </p>
                <div className="space-y-2 text-sm text-muted-foreground">
                  <div className="flex items-center gap-2">
                    <Eye className="h-3.5 w-3.5 text-primary" />
                    <span>Per-field visibility controls</span>
                  </div>
                  <div className="flex items-center gap-2">
                    <Users className="h-3.5 w-3.5 text-primary" />
                    <span>Recipient-based permissions</span>
                  </div>
                  <div className="flex items-center gap-2">
                    <Clock className="h-3.5 w-3.5 text-primary" />
                    <span>Time-limited access tokens</span>
                  </div>
                </div>
              </div>
            </motion.div>
          </motion.div>
        </div>
      </section>

      {/* How It Works */}
      <section className="py-24 px-6">
        <div className="container mx-auto max-w-4xl">
          <motion.div
            initial={{ opacity: 0, y: 20 }}
            whileInView={{ opacity: 1, y: 0 }}
            viewport={{ once: true }}
            className="text-center mb-16"
          >
            <Badge variant="outline" className="mb-4">
              How It Works
            </Badge>
            <h2 className="text-3xl md:text-4xl font-bold mb-4">
              Three simple steps
            </h2>
          </motion.div>
          
          <motion.div
            variants={staggerContainer}
            initial="initial"
            whileInView="animate"
            viewport={{ once: true }}
            className="space-y-8"
          >
            {[
              {
                step: "01",
                title: "Connect Your Sources",
                description: "Link your AI conversations, Notion pages, Facebook data, and local files."
              },
              {
                step: "02",
                title: "Index Everything",
                description: "MindSage processes and indexes your content locally using AI embeddings."
              },
              {
                step: "03",
                title: "Search & Explore",
                description: "Find anything instantly with semantic search or browse your knowledge graph."
              }
            ].map((item) => (
              <motion.div
                key={item.step}
                variants={fadeInUp}
                className="flex gap-6 items-start p-6 rounded-xl border border-border bg-card/50"
              >
                <div className="flex-shrink-0 text-3xl font-bold text-primary font-mono">
                  {item.step}
                </div>
                <div>
                  <h3 className="font-semibold text-lg mb-1">{item.title}</h3>
                  <p className="text-muted-foreground">{item.description}</p>
                </div>
              </motion.div>
            ))}
          </motion.div>
        </div>
      </section>

      {/* CTA Section */}
      <section className="py-24 px-6">
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          whileInView={{ opacity: 1, y: 0 }}
          viewport={{ once: true }}
          className="container mx-auto max-w-3xl text-center"
        >
          <div id="get-started" className="p-12 rounded-2xl border border-border bg-gradient-to-br from-primary/10 via-transparent to-transparent scroll-mt-24">
            <Shield className="h-12 w-12 text-primary mx-auto mb-6" />
            <h2 className="text-3xl md:text-4xl font-bold mb-4">
              Ready to own your knowledge?
            </h2>
            <p className="text-muted-foreground mb-8 max-w-lg mx-auto">
              Start building your private knowledge base today. No account required, no cloud dependencies.
            </p>
            <Link to="/dashboard">
              <Button size="lg" className="gap-2 h-12 px-8">
                Open Dashboard
                <ArrowRight className="h-4 w-4" />
              </Button>
            </Link>
          </div>
        </motion.div>
      </section>

      {/* Footer */}
      <footer className="py-8 px-6 border-t border-border">
        <div className="container mx-auto max-w-6xl flex flex-col md:flex-row items-center justify-between gap-4">
          <div className="flex items-center gap-2">
            <Brain className="h-5 w-5 text-primary" />
            <span className="font-medium">MindSage</span>
          </div>
          <div className="flex items-center gap-6 text-sm text-muted-foreground">
            <Link to="/dashboard" className="hover:text-foreground transition-colors">Dashboard</Link>
            <Link to="/explore" className="hover:text-foreground transition-colors">Explore</Link>
            <a href="https://github.com/nicholasgriffintn/mindsage" target="_blank" rel="noopener noreferrer" className="hover:text-foreground transition-colors">GitHub</a>
          </div>
          <p className="text-sm text-muted-foreground">
            Privacy-first personal knowledge management
          </p>
        </div>
      </footer>
    </div>
  );
}
