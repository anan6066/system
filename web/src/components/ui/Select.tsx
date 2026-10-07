import React from 'react';
import * as SelectPrimitive from '@radix-ui/react-select';
import { ChevronDown, Check } from 'lucide-react';

interface SelectOption {
  value: string;
  label: string;
  description?: string;
}

interface SelectProps {
  value: string;
  onValueChange: (value: string) => void;
  options: SelectOption[];
  placeholder?: string;
  label?: string;
  className?: string;
}

export const Select: React.FC<SelectProps> = ({
  value,
  onValueChange,
  options,
  placeholder = '请选择...',
  label,
  className = ''
}) => {
  return (
    <div className={`w-full ${className}`}>
      {label && (
        <label className="block text-sm font-semibold text-slate-700 dark:text-slate-300 mb-2">
          {label}
        </label>
      )}
      <SelectPrimitive.Root value={value} onValueChange={onValueChange}>
        <SelectPrimitive.Trigger className="
          w-full flex items-center justify-between
          bg-slate-50 dark:bg-dark-800/50 border border-slate-200 dark:border-dark-700 rounded-xl
          px-4 py-2.5 text-slate-700 dark:text-slate-200
          focus:outline-none focus:border-brand-500 focus:ring-2 focus:ring-brand-500/20
          transition-all duration-200
        ">
          <SelectPrimitive.Value placeholder={placeholder} />
          <SelectPrimitive.Icon>
            <ChevronDown className="w-4 h-4 text-slate-400" />
          </SelectPrimitive.Icon>
        </SelectPrimitive.Trigger>
        
        <SelectPrimitive.Portal>
          <SelectPrimitive.Content className="
            overflow-hidden bg-white dark:bg-dark-800 border border-slate-200 dark:border-dark-700 rounded-xl shadow-2xl
            z-50
          ">
            <SelectPrimitive.Viewport className="p-1">
              {options.map((option) => (
                <SelectPrimitive.Item
                  key={option.value}
                  value={option.value}
                  className="
                    relative flex items-center gap-2
                    px-4 py-2.5 rounded-lg text-slate-700 dark:text-slate-200
                    cursor-pointer select-none
                    outline-none
                    data-[highlighted]:bg-brand-50 dark:data-[highlighted]:bg-brand-500/20
                    data-[state=checked]:text-brand-600 dark:data-[state=checked]:text-brand-400
                  "
                >
                  <SelectPrimitive.ItemIndicator>
                    <Check className="w-4 h-4 text-brand-500" />
                  </SelectPrimitive.ItemIndicator>
                  <div>
                    <SelectPrimitive.ItemText>
                      {option.label}
                    </SelectPrimitive.ItemText>
                    {option.description && (
                      <p className="text-xs text-slate-500 dark:text-slate-400">{option.description}</p>
                    )}
                  </div>
                </SelectPrimitive.Item>
              ))}
            </SelectPrimitive.Viewport>
          </SelectPrimitive.Content>
        </SelectPrimitive.Portal>
      </SelectPrimitive.Root>
    </div>
  );
};
