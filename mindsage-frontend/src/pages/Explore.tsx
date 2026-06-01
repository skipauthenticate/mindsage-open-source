import { motion } from 'framer-motion';
import { PageContainer } from '@/components/layout/PageContainer';
import { KnowledgeGraph } from '@/components/graph/KnowledgeGraph';

const Explore = () => {
  return (
    <PageContainer className="h-[calc(100vh-3.5rem)] flex flex-col p-0">
      <motion.div
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        className="flex-1 min-h-0"
      >
        <KnowledgeGraph />
      </motion.div>
    </PageContainer>
  );
};

export default Explore;
