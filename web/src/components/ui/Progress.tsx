import React from 'react';
import * as ProgressPrimitive from '@radix-ui/react-progress';

interface ProgressProps {
  value: number;
  max?: number;
  variant?: 'default' | 'success' | 'warning' | 'error';
  showLabel?: boolean;
  className?: string;
}

export const Progress: React.FC<ProgressProps> = ({
  value,
  max = 100,
  variant = 'default',
  showLabel = false,
  className = ''
}) => {
  const percentage = Math.min(Math.max((value / max) * 100, 0), 100);
  
  const variants = {
    default: 'bg-slate-800 dark:bg-slate-200',
    success: 'bg-emerald-500',
    warning: 'bg-amber-500',
    error: 'bg-red-500'
  };

  return (
    <div className={`w-full ${className}`}>
      <ProgressPrimitive.Root
        className="relative overflow-hidden bg-slate-200 dark:bg-dark-700 rounded-full h-2"
        value={percentage}
      >
        <ProgressPrimitive.Indicator
          className={`h-full rounded-full transition-all duration-300 ${variants[variant]}`}
          style={{ width: `${percentage}%` }}
        />
      </ProgressPrimitive.Root>
      {showLabel && (
        <div className="flex justify-between mt-1.5 text-xs text-slate-500 dark:text-slate-400">
          <span>{value}</span>
          <span>{max}</span>
        </div>
      )}
    </div>
  );
};
