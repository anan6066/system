import React from 'react';
import { motion } from 'framer-motion'; 
import { 
  Home,
  Cpu, 
  Rocket, 
  GitCompare, 
  LayoutDashboard, 
  ChevronLeft,
  ChevronRight,
  Zap
} from 'lucide-react';
import { useAppStore } from '../../store/appStore';
import { ThemeToggle } from '../ui/ThemeToggle';

interface NavItem {
  id: string;
  label: string;
  icon: React.ReactNode;
  path: string;
}

const navItems: NavItem[] = [
  { id: 'home', label: '首页', icon: <Home className="w-5 h-5" />, path: '/home' },
  { id: 'quantization', label: '模型量化', icon: <Cpu className="w-5 h-5" />, path: '/quantization' },
  { id: 'deployment', label: '一键部署', icon: <Rocket className="w-5 h-5" />, path: '/deployment' },
  { id: 'comparison', label: '效果对比', icon: <GitCompare className="w-5 h-5" />, path: '/comparison' },
  { id: 'devices', label: '设备管理', icon: <LayoutDashboard className="w-5 h-5" />, path: '/devices' },
];

export const Sidebar: React.FC = () => {
  const { currentPage, setCurrentPage, sidebarCollapsed, toggleSidebar } = useAppStore();

  return (
    <motion.aside
      initial={false}
      animate={{ width: sidebarCollapsed ? 80 : 260 }}
      transition={{ duration: 0.3, ease: 'easeInOut' }}
      className="
        fixed left-0 top-0 h-screen
        bg-slate-900 dark:bg-slate-950
        border-r border-slate-800 dark:border-slate-800
        z-40 flex flex-col
      "
    >
      {/* Logo */}
      <div className="p-5 border-b border-slate-800">
        <motion.div 
          className="flex items-center gap-3"
          animate={{ justifyContent: sidebarCollapsed ? 'center' : 'flex-start' }}
        >
          <div className="w-9 h-9 rounded-lg bg-slate-800 dark:bg-slate-700 flex items-center justify-center">
            <Zap className="w-5 h-5 text-white" />
          </div>
          {!sidebarCollapsed && (
            <motion.div
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
            >
              <h1 className="text-lg font-bold text-white">NPU Quant</h1>
              <p className="text-xs text-slate-400">模型量化部署平台</p>
            </motion.div>
          )}
        </motion.div>
      </div>

      {/* Navigation */}
      <nav className="flex-1 p-3 space-y-1">
        {navItems.map((item) => (
          <motion.button
            key={item.id}
            onClick={() => setCurrentPage(item.id)}
            className={`
              w-full flex items-center gap-3 px-4 py-2.5 rounded-lg
              transition-all duration-150
              ${currentPage === item.id 
                ? 'bg-slate-800 text-white' 
                : 'text-slate-400 hover:bg-slate-800/50 hover:text-white'
              }
              ${sidebarCollapsed ? 'justify-center' : ''}
            `}
            whileHover={{ x: 2 }}
            whileTap={{ scale: 0.98 }}
          >
            {item.icon}
            {!sidebarCollapsed && (
              <span className="font-medium text-sm">{item.label}</span>
            )}
          </motion.button>
        ))}
      </nav>

      {/* Theme Toggle */}
      <div className={`px-3 py-2 ${sidebarCollapsed ? 'flex justify-center' : ''}`}>
        <ThemeToggle />
      </div>

      {/* Bottom Section */}
      <div className="p-3 border-t border-slate-800">
        <motion.button
          onClick={toggleSidebar}
          className="
            w-full flex items-center justify-center gap-2
            px-3 py-2 rounded-lg
            text-slate-500 hover:bg-slate-800 hover:text-white
            transition-all duration-150
          "
          whileHover={{ scale: 1.02 }}
          whileTap={{ scale: 0.98 }}
        >
          {sidebarCollapsed ? (
            <ChevronRight className="w-4 h-4" />
          ) : (
            <>
              <ChevronLeft className="w-4 h-4" />
              <span className="text-sm">收起</span>
            </>
          )}
        </motion.button>
      </div>
    </motion.aside>
  );
};
