import React from 'react';
import { motion } from 'framer-motion';
import { Sun, Moon } from 'lucide-react';
import { useAppStore } from '../../store/appStore';

export const ThemeToggle: React.FC = () => {
  const { theme, toggleTheme } = useAppStore();

  return (
    <motion.button
      onClick={toggleTheme}
      className={`
        relative w-14 h-8 rounded-full p-1
        transition-colors duration-300
        ${theme === 'dark' 
          ? 'bg-slate-700' 
          : 'bg-amber-200'
        }
      `}
      whileTap={{ scale: 0.95 }}
    >
      <motion.div
        className={`
          w-6 h-6 rounded-full flex items-center justify-center
          ${theme === 'dark'
            ? 'bg-gradient-to-br from-indigo-500 to-violet-600'
            : 'bg-gradient-to-br from-amber-400 to-orange-500'
          }
        `}
        animate={{ 
          x: theme === 'dark' ? 24 : 0
        }}
        transition={{ type: 'spring', stiffness: 500, damping: 30 }}
      >
        {theme === 'dark' ? (
          <Moon className="w-3.5 h-3.5 text-white" />
        ) : (
          <Sun className="w-3.5 h-3.5 text-white" />
        )}
      </motion.div>
    </motion.button>
  );
};
