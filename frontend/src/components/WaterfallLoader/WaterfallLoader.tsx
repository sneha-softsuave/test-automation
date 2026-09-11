import { useState, useEffect, useRef } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import styles from './WaterfallLoader.module.css';

export interface WaterfallLoaderProps {
  intervalMs?: number;
  compact?: boolean;
}

const WORDS = [
  'Generating', 'Thinking', 'Analyzing', 'Processing', 'Synthesizing',
  'Reviewing', 'Computing', 'Exploring', 'Organizing', 'Optimizing',
  'Interpreting', 'Compiling', 'Evaluating', 'Calculating', 'Strategizing',
  'Structuring', 'Decoding', 'Preparing', 'Summarizing', 'Visualizing',
  'Formulating', 'Inferring', 'Mapping', 'Assessing', 'Crafting',
];

export function WaterfallLoader({ intervalMs = 1500, compact = false }: WaterfallLoaderProps) {
  const [index, setIndex] = useState(() => Math.floor(Math.random() * WORDS.length));
  const indexRef = useRef(index);

  useEffect(() => {
    const timer = setInterval(() => {
      indexRef.current = (indexRef.current + 1) % WORDS.length;
      setIndex(indexRef.current);
    }, intervalMs);
    return () => clearInterval(timer);
  }, [intervalMs]);

  return (
    <div className={`${styles.root} ${compact ? styles.compact : ''}`}>
      <AnimatePresence mode="wait">
        <motion.span
          key={index}
          className={styles.word}
          initial={{ opacity: 0, y: 6 }}
          animate={{ opacity: 1, y: 0 }}
          exit={{ opacity: 0, y: -6 }}
          transition={{ duration: 0.25, ease: 'easeInOut' }}
        >
          {WORDS[index]}
        </motion.span>
      </AnimatePresence>
      <span className={styles.dots}>
        <span className={styles.dot} />
        <span className={styles.dot} />
        <span className={styles.dot} />
      </span>
    </div>
  );
}
