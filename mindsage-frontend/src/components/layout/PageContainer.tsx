import { motion } from 'framer-motion';
import { cn } from '@/lib/utils';

interface PageContainerProps {
  children: React.ReactNode;
  className?: string;
}

export function PageContainer({ children, className }: PageContainerProps) {
  return (
    <motion.main
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      transition={{ duration: 0.3 }}
      className={cn(
        'container mx-auto px-4 py-6 md:px-6 md:py-8',
        className
      )}
    >
      {children}
    </motion.main>
  );
}
