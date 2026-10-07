import React from 'react';

interface InputProps extends React.InputHTMLAttributes<HTMLInputElement> {
  label?: string;
  error?: string;
  icon?: React.ReactNode;
}

export const Input: React.FC<InputProps> = ({
  label,
  error,
  icon,
  className = '',
  ...props
}) => {
  return (
    <div className="w-full">
      {label && (
        <label className="block text-sm font-semibold text-slate-700 dark:text-slate-300 mb-2">
          {label}
        </label>
      )}
      <div className="relative">
        {icon && (
          <div className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400 dark:text-slate-500">
            {icon}
          </div>
        )}
        <input
          className={`
            w-full bg-slate-50 dark:bg-dark-800/50 border border-slate-200 dark:border-dark-700 rounded-xl
            text-slate-800 dark:text-slate-200 placeholder-slate-400 dark:placeholder-slate-500
            px-4 py-2.5 ${icon ? 'pl-10' : ''}
            focus:outline-none focus:border-brand-500 focus:ring-2 focus:ring-brand-500/20
            transition-all duration-200
            ${error ? 'border-red-500' : ''}
            ${className}
          `}
          {...props}
        />
      </div>
      {error && (
        <p className="mt-1.5 text-sm text-red-500">{error}</p>
      )}
    </div>
  );
};
