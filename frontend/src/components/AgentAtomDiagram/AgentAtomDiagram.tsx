import { motion } from 'framer-motion';
import { Brain, Code, Zap, Shield, FileCheck } from 'lucide-react';
import type { ActiveAgent } from '../../hooks/useExecutionWebSocket';
import styles from './AgentAtomDiagram.module.css';

interface AgentAtomDiagramProps {
  currentAgent: ActiveAgent;
  isExecuting: boolean;
}

const agentConfig = {
  Parser: { icon: Code, color: '#9333ea', label: 'Parser' },
  Validator: { icon: Shield, color: '#f59e0b', label: 'Validator' },
  Executor: { icon: Zap, color: '#3b82f6', label: 'Executor' },
  Reporter: { icon: FileCheck, color: '#10b981', label: 'Reporter' },
} as const;

export const AgentAtomDiagram = ({ currentAgent, isExecuting }: AgentAtomDiagramProps) => {
  if (!isExecuting) return null;

  const isSupervisorActive = currentAgent === 'Supervisor';

  return (
    <motion.div
      className={styles.atomContainer}
      initial={{ opacity: 0, scale: 0.8 }}
      animate={{ opacity: 1, scale: 1 }}
      exit={{ opacity: 0, scale: 0.8 }}
      transition={{ duration: 0.4 }}
    >
      <div className={styles.atom}>
        {/* Connection lines SVG - stays static behind everything */}
        <svg className={styles.connections} viewBox="0 0 180 180">
          {[
            { angle: -90, agent: 'Parser' },    // Top
            { angle: 0, agent: 'Validator' },   // Right
            { angle: 90, agent: 'Executor' },   // Bottom
            { angle: 180, agent: 'Reporter' },  // Left
          ].map(({ angle, agent }) => {
            const isActive = currentAgent === agent;
            const rad = (angle * Math.PI) / 180;
            const x2 = 90 + 60 * Math.cos(rad);
            const y2 = 90 + 60 * Math.sin(rad);

            return (
              <motion.line
                key={agent}
                x1="90"
                y1="90"
                x2={x2}
                y2={y2}
                className={`${styles.connectionLine} ${isActive ? styles.activeConnection : ''}`}
                strokeDasharray="5 5"
                animate={isActive ? {
                  strokeOpacity: [0.4, 1, 0.4],
                  strokeWidth: [1.5, 3, 1.5],
                } : {
                  strokeOpacity: 0.2,
                  strokeWidth: 1,
                }}
                transition={{ duration: 0.6, repeat: isActive ? Infinity : 0 }}
              />
            );
          })}
        </svg>

        {/* Nucleus Wrapper - handles positioning */}
        <div className={styles.nucleusWrapper}>
          {/* Nucleus - handles animation */}
          <motion.div
            className={`${styles.nucleus} ${isSupervisorActive ? styles.active : ''}`}
            animate={isSupervisorActive ? {
              scale: [1, 1.15, 1],
              boxShadow: [
                '0 0 20px rgba(34, 197, 94, 0.5)',
                '0 0 50px rgba(34, 197, 94, 1), 0 0 80px rgba(34, 197, 94, 0.6)',
                '0 0 20px rgba(34, 197, 94, 0.5)',
              ],
            } : {
              scale: 1,
              boxShadow: '0 0 20px rgba(34, 197, 94, 0.5)',
            }}
            transition={{ duration: 0.8, repeat: isSupervisorActive ? Infinity : 0, ease: "easeInOut" }}
          >
            <Brain size={22} />
            <span className={styles.nucleusLabel}>Supervisor</span>
          </motion.div>
        </div>

        {/* Rotating Orbit with agents */}
        <div className={styles.orbit}>
          {(Object.entries(agentConfig) as [keyof typeof agentConfig, typeof agentConfig[keyof typeof agentConfig]][]).map(([agentName, config]) => {
            const isActive = currentAgent === agentName;
            const Icon = config.icon;

            return (
              // Wrapper handles positioning and counter-rotation
              <div
                key={agentName}
                className={styles.agentWrapper}
                style={{ '--agent-color': config.color } as React.CSSProperties}
              >
                {/* Inner node handles scale animation */}
                <motion.div
                  className={`${styles.agentNode} ${isActive ? styles.active : ''}`}
                  style={{ '--agent-color': config.color } as React.CSSProperties}
                  animate={isActive ? {
                    scale: [1, 1.35, 1],
                    boxShadow: [
                      `0 0 15px ${config.color}`,
                      `0 0 45px ${config.color}, 0 0 70px ${config.color}80`,
                      `0 0 15px ${config.color}`,
                    ],
                  } : {
                    scale: 1,
                    boxShadow: `0 0 12px ${config.color}80`,
                  }}
                  transition={{
                    duration: 0.7,
                    repeat: isActive ? Infinity : 0,
                    ease: "easeInOut"
                  }}
                >
                  <Icon size={16} />
                  <span className={styles.agentLabel}>{config.label}</span>
                </motion.div>
              </div>
            );
          })}
        </div>
      </div>

      {/* Status indicator */}
      <motion.div
        className={styles.statusBar}
        initial={{ opacity: 0, y: 10 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.2 }}
      >
        <motion.span
          className={styles.statusDot}
          animate={{
            scale: [1, 1.3, 1],
            opacity: [1, 0.6, 1],
          }}
          transition={{ duration: 1.2, repeat: Infinity }}
        />
        <span className={styles.statusText}>
          {currentAgent ? `${currentAgent} Active` : 'Initializing...'}
        </span>
      </motion.div>
    </motion.div>
  );
};
