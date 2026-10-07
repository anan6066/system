import React from 'react';

interface BadgeProps {
  variant?: 'default' | 'success' | 'warning' | 'error' | 'info';
  children: React.ReactNode;
  className?: string;
}

export const Badge: React.FC<BadgeProps> = ({
  variant = 'default',
  children,
  className = ''
}) => {
  const variants = {
    default: 'bg-slate-200/80 dark:bg-dark-700 text-slate-600 dark:text-slate-300',
    success: 'bg-emerald-100/80 dark:bg-emerald-500/20 text-emerald-700 dark:text-emerald-400',
    warning: 'bg-amber-100/80 dark:bg-amber-500/20 text-amber-700 dark:text-amber-400',
    error: 'bg-red-100/80 dark:bg-red-500/20 text-red-700 dark:text-red-400',
    info: 'bg-slate-800 dark:bg-slate-200 text-white dark:text-slate-800'
  };

  return (
    <span className={`
      inline-flex items-center gap-1 px-2 py-0.5 rounded-md text-xs font-medium
      ${variants[variant]} ${className}
    `}>
      {children}
    </span>
  );
};
