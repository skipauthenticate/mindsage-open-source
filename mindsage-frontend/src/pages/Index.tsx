import { motion } from 'framer-motion';
import { PageContainer } from '@/components/layout/PageContainer';
import { FileTransferPanel } from '@/components/home/FileTransferPanel';
import { MCPSetupPanel } from '@/components/home/MCPSetupPanel';
import { ConnectorGrid } from '@/components/home/ConnectorGrid';
import { ChatPanel } from '@/components/chat/ChatPanel';

const Index = () => {
  return (
    <PageContainer>
      <motion.div
        initial={{ opacity: 0, y: 8 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.3 }}
        className="grid grid-cols-1 lg:grid-cols-3 gap-6"
      >
        {/* Chat Panel — shows first on mobile, right column on desktop */}
        <motion.div
          initial={{ opacity: 0, y: 8 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.05 }}
          className="order-first lg:order-last lg:col-span-2 lg:row-span-2"
        >
          <div className="h-[calc(100vh-10rem)] min-h-[400px] max-h-[800px]">
            <ChatPanel />
          </div>
        </motion.div>

        {/* Left Column: File Transfer + Connectors + MCP */}
        <div className="lg:col-span-1 space-y-6 order-last lg:order-first">
          <motion.div
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: 0.08 }}
          >
            <FileTransferPanel />
          </motion.div>

          <motion.div
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: 0.1 }}
          >
            <ConnectorGrid />
          </motion.div>

          <motion.div
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: 0.12 }}
          >
            <MCPSetupPanel />
          </motion.div>
        </div>
      </motion.div>
    </PageContainer>
  );
};

export default Index;
