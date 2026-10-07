import React from 'react';
import { motion } from 'framer-motion';

interface CardProps {
  children: React.ReactNode;
  className?: string;
  hover?: boolean;
  onClick?: () => void;
  variant?: 'default' | 'glass' | 'bordered';
}

export const Card: React.FC<CardProps> = ({ 
  children, 
  className = '', 
  hover = false,
  onClick,
  variant = 'default'
}) => {
  const variants = {
    default: 'bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-700',
    glass: 'bg-white/70 dark:bg-slate-800/50 backdrop-blur-xl border border-slate-100 dark:border-slate-700/30',
    bordered: 'bg-transparent border-2 border-slate-200 dark:border-slate-700'
  };

  return (
    <motion.div
      whileHover={hover ? { y: -2 } : {}}
      transition={{ duration: 0.2 }}
      onClick={onClick}
      className={`
        rounded-2xl p-5 shadow-sm
        ${variants[variant]}
        ${hover ? 'cursor-pointer hover:shadow-md hover:border-slate-300 dark:hover:border-dark-600' : ''}
        ${className}
      `}
    >
      {children}
    </motion.div>
  );
};
