import React, { useEffect } from 'react';
import { motion } from 'framer-motion';
import {
  Rocket,
  GitCompare,
  LayoutDashboard,
  Zap,
  Server,
  BarChart3,
  Shield,
  Cloud,
  ArrowRight,
  Layers,
  Gauge,
  RefreshCw,
  AlertCircle,
  Cpu,
} from 'lucide-react';
import { Card, Button } from '../components/ui';
import { useAppStore } from '../store/appStore';

export const HomePage: React.FC = () => {
  const { setCurrentPage, stats, statsLoading, statsError, fetchStats } = useAppStore();

  useEffect(() => {
    void fetchStats();
  }, [fetchStats]);

  const features = [
    {
      id: 'quantization',
      icon: <Cpu className="w-6 h-6" />,
      title: '智能模型量化',
      description: '支持 ONNX 模型一键量化，智能区分 INT8/FP16 层，自动生成混合精度方案',
      stats: '4+ 预设模型',
    },
    {
      id: 'deployment',
      icon: <Rocket className="w-6 h-6" />,
      title: '一键部署',
      description: '选择目标设备即可推送量化模型，自动采集推理速度、内存占用等关键指标',
      stats: '2+ NPU 支持',
    },
    {
      id: 'comparison',
      icon: <GitCompare className="w-6 h-6" />,
      title: '效果对比分析',
      description: '可视化展示量化前后性能差异，雷达图、柱状图多维度呈现优化效果',
      stats: '5+ 评估指标',
    },
    {
      id: 'devices',
      icon: <LayoutDashboard className="w-6 h-6" />,
      title: '设备管理',
      description: '集中管理多台 NPU 开发板，实时监控连接状态与资源占用',
      stats: '实时监控',
    },
  ];

  // 首页四个统计卡：全部来自 GET /api/stats 的真实聚合
  const statCards = [
    {
      label: '活跃设备',
      value: stats ? `${stats.activeDevices}/${stats.totalDevices}` : '—',
      hint: stats && stats.busyDevices > 0 ? `${stats.busyDevices} 台忙碌中` : '在线 / 总数',
      icon: <Server className="w-5 h-5" />,
    },
    {
      label: '已量化模型',
      value: stats ? String(stats.quantizedModels) : '—',
      hint: stats ? `共 ${stats.totalModels} 个模型` : '量化完成',
      icon: <Layers className="w-5 h-5" />,
    },
    {
      label: '部署次数',
      value: stats ? String(stats.totalDeployments) : '—',
      hint: stats ? `成功 ${stats.successfulDeployments} 次` : '推送记录',
      icon: <Rocket className="w-5 h-5" />,
    },
    {
      label: '平均延迟',
      value: stats?.avgLatencyMs != null ? `${stats.avgLatencyMs.toFixed(1)}ms` : '—',
      hint: stats?.avgTop1Accuracy != null ? `平均准确率 ${stats.avgTop1Accuracy.toFixed(1)}%` : '暂无实测数据',
      icon: <Gauge className="w-5 h-5" />,
    },
  ];

  return (
    <div className="max-w-7xl mx-auto">
      {/* Hero Section */}
      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        className="relative mb-16"
      >
        {/* Background - Subtle pattern */}
        <div className="absolute inset-0 overflow-hidden pointer-events-none">
          <div className="absolute top-0 right-0 w-[600px] h-[600px] bg-slate-100 dark:bg-dark-800/50 rounded-full blur-3xl opacity-50" />
          <div className="absolute bottom-0 left-0 w-[400px] h-[400px] bg-slate-50 dark:bg-dark-900 rounded-full blur-3xl opacity-40" />
        </div>

        <div className="relative pt-8 pb-16">
          <motion.div
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: 0.1 }}
            className="flex items-center gap-3 mb-6"
          >
            <div className="w-12 h-12 rounded-xl bg-slate-800 dark:bg-slate-200 flex items-center justify-center">
              <Zap className="w-6 h-6 text-white dark:text-slate-800" />
            </div>
            <span className="px-3 py-1 bg-slate-100 dark:bg-dark-800 text-slate-600 dark:text-slate-400 text-sm font-medium rounded-full">
              NPU Model Quantization Platform
            </span>
          </motion.div>

          <motion.h1
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: 0.2 }}
            className="text-4xl md:text-5xl font-bold text-slate-800 dark:text-white mb-6 leading-tight"
          >
            智能模型量化
            <br />
            <span className="text-slate-600 dark:text-slate-300">
              部署一体化平台
            </span>
          </motion.h1>

          <motion.p
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: 0.3 }}
            className="text-lg text-slate-500 dark:text-slate-400 max-w-2xl mb-8 leading-relaxed"
          >
            专注于边缘计算的 AI 模型量化与部署解决方案。支持主流 NPU 芯片，
            智能生成混合精度量化方案，一键部署并实时监控性能指标。
          </motion.p>

          <motion.div
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: 0.4 }}
            className="flex flex-wrap gap-3"
          >
            <Button
              onClick={() => setCurrentPage('quantization')}
              icon={<Zap className="w-4 h-4" />}
            >
              开始量化
            </Button>
            <Button
              variant="secondary"
              onClick={() => setCurrentPage('devices')}
              icon={<Server className="w-4 h-4" />}
            >
              管理设备
            </Button>
          </motion.div>
        </div>
      </motion.div>

      {/* Stats */}
      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.5 }}
        className="mb-16"
      >
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-sm font-semibold text-slate-500 dark:text-slate-400">
            平台概览
          </h2>
          <Button
            variant="ghost"
            size="sm"
            onClick={() => void fetchStats()}
            loading={statsLoading}
            icon={<RefreshCw className="w-3.5 h-3.5" />}
          >
            刷新
          </Button>
        </div>

        {statsError && (
          <div className="mb-4 flex items-start gap-2 rounded-xl border border-amber-300/60 bg-amber-50 dark:border-amber-500/30 dark:bg-amber-500/10 px-4 py-3 text-sm text-amber-700 dark:text-amber-300">
            <AlertCircle className="w-4 h-4 mt-0.5 flex-shrink-0" />
            <span>统计数据加载失败：{statsError}</span>
          </div>
        )}

        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          {statCards.map((stat) => (
            <Card key={stat.label} className="text-center py-5">
              <div className="w-10 h-10 rounded-xl bg-slate-100 dark:bg-dark-800 flex items-center justify-center mx-auto mb-3 text-slate-600 dark:text-slate-400">
                {stat.icon}
              </div>
              <p className="text-3xl font-bold text-slate-800 dark:text-white">{stat.value}</p>
              <p className="text-sm text-slate-500 dark:text-slate-400">{stat.label}</p>
              <p className="text-xs text-slate-400 dark:text-slate-500 mt-1">{stat.hint}</p>
            </Card>
          ))}
        </div>
      </motion.div>

      {/* Features */}
      <div className="mb-16">
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.6 }}
          className="text-center mb-12"
        >
          <h2 className="text-2xl font-bold text-slate-800 dark:text-white mb-3">核心功能</h2>
          <p className="text-slate-500 dark:text-slate-400 max-w-xl mx-auto">
            完整的模型量化与部署工作流，满足边缘计算场景下的各类需求
          </p>
        </motion.div>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {features.map((feature, index) => (
            <motion.div
              key={feature.id}
              initial={{ opacity: 0, y: 20 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: 0.7 + index * 0.1 }}
            >
              <Card
                hover
                className="h-full cursor-pointer"
                onClick={() => setCurrentPage(feature.id)}
              >
                <div className="flex items-start gap-4">
                  <div className="w-12 h-12 rounded-xl bg-slate-800 dark:bg-slate-200 flex items-center justify-center text-white dark:text-slate-800 flex-shrink-0">
                    {feature.icon}
                  </div>
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center justify-between mb-2">
                      <h3 className="text-lg font-semibold text-slate-800 dark:text-white">{feature.title}</h3>
                      <ArrowRight className="w-4 h-4 text-slate-400 flex-shrink-0" />
                    </div>
                    <p className="text-sm text-slate-500 dark:text-slate-400 mb-3">{feature.description}</p>
                    <span className="inline-flex items-center px-2.5 py-1 bg-slate-100 dark:bg-dark-800 text-slate-600 dark:text-slate-400 text-xs font-medium rounded-md">
                      {feature.stats}
                    </span>
                  </div>
                </div>
              </Card>
            </motion.div>
          ))}
        </div>
      </div>

      {/* Benefits */}
      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 1.1 }}
      >
        <Card className="bg-slate-800 dark:bg-slate-900 overflow-hidden">
          <div className="grid grid-cols-1 md:grid-cols-3 gap-8 py-6">
            <div className="flex items-start gap-4">
              <div className="w-10 h-10 rounded-lg bg-slate-200 dark:bg-white/10 flex items-center justify-center flex-shrink-0">
                <Shield className="w-5 h-5 text-slate-600 dark:text-slate-300" />
              </div>
              <div>
                <h4 className="font-semibold text-slate-800 dark:text-white mb-1">真实链路</h4>
                <p className="text-slate-600 dark:text-slate-400 text-sm">SSH 探活与指标采集、SFTP 推送均对接真机</p>
              </div>
            </div>
            <div className="flex items-start gap-4">
              <div className="w-10 h-10 rounded-lg bg-slate-200 dark:bg-white/10 flex items-center justify-center flex-shrink-0">
                <Cloud className="w-5 h-5 text-slate-600 dark:text-slate-300" />
              </div>
              <div>
                <h4 className="font-semibold text-slate-800 dark:text-white mb-1">云边协同</h4>
                <p className="text-slate-600 dark:text-slate-400 text-sm">云端量化，边缘部署，全流程进度可追踪</p>
              </div>
            </div>
            <div className="flex items-start gap-4">
              <div className="w-10 h-10 rounded-lg bg-slate-200 dark:bg-white/10 flex items-center justify-center flex-shrink-0">
                <BarChart3 className="w-5 h-5 text-slate-600 dark:text-slate-300" />
              </div>
              <div>
                <h4 className="font-semibold text-slate-800 dark:text-white mb-1">可视化分析</h4>
                <p className="text-slate-600 dark:text-slate-400 text-sm">多维度性能指标采集与混合精度效果对比</p>
              </div>
            </div>
          </div>
        </Card>
      </motion.div>
    </div>
  );
};
