import React, { useEffect, useMemo, useState } from 'react';
import { motion } from 'framer-motion';
import {
  GitCompare,
  TrendingUp,
  Clock,
  HardDrive,
  Zap,
  Award,
  BarChart3,
  Activity,
  Target,
  AlertCircle,
  Loader2,
} from 'lucide-react';
import {
  RadarChart,
  PolarGrid,
  PolarAngleAxis,
  PolarRadiusAxis,
  Radar,
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ResponsiveContainer,
} from 'recharts';
import { Card, Badge, Select } from '../components/ui';
import { useAppStore } from '../store/appStore';

export const ComparisonPage: React.FC = () => {
  const {
    models,
    devices,
    deployments,
    fetchDeployments,
    comparison,
    comparisonLoading,
    comparisonError,
    fetchComparison,
    clearComparison,
    theme,
  } = useAppStore();
  const [selectedDeploymentId, setSelectedDeploymentId] = useState('');

  useEffect(() => {
    void fetchDeployments();
  }, [fetchDeployments]);

  // 只有成功且有指标数据的部署记录才能做对比
  const successfulDeployments = useMemo(
    () => deployments.filter((item) => item.status === 'success' && item.metrics),
    [deployments],
  );

  // 默认选中最近一次成功部署
  useEffect(() => {
    if (selectedDeploymentId) return;
    if (successfulDeployments.length > 0) {
      setSelectedDeploymentId(successfulDeployments[0].id);
    }
  }, [successfulDeployments, selectedDeploymentId]);

  // 对比数据由后端计算：基线 = 同一模型全部层 INT8，混合 = 用户实际选定的位宽组合
  useEffect(() => {
    if (!selectedDeploymentId) {
      clearComparison();
      return;
    }
    void fetchComparison({ deploymentId: selectedDeploymentId });
  }, [selectedDeploymentId, fetchComparison, clearComparison]);

  const comparisonData = comparison?.rows ?? [];
  const radarData = comparison?.radar ?? [];

  const deploymentOptions = successfulDeployments.map((item) => {
    const model = models.find((m) => m.id === item.modelId);
    const device = devices.find((dev) => dev.id === item.deviceId);
    return {
      value: item.id,
      label: `${item.modelName ?? model?.name ?? '未知模型'} → ${item.deviceName ?? device?.name ?? '未知设备'}`,
      description: `推理: ${item.metrics ? item.metrics.inferenceSpeed.toFixed(1) : '—'}ms | 准确率: ${
        item.metrics ? item.metrics.top1Accuracy.toFixed(1) : '—'
      }%`,
    };
  });

  const rowOf = (keyword: string) =>
    comparisonData.find((row) => row.metric.includes(keyword)) ?? null;

  const accuracyRow = rowOf('准确率');
  const latencyRow = rowOf('延迟');
  const memoryRow = rowOf('内存');
  const powerRadar = radarData.find((item) => item.metric === '功耗') ?? null;

  const signed = (value: number) => `${value >= 0 ? '+' : ''}${value.toFixed(1)}`;

  const accuracyImprovement = accuracyRow
    ? signed(accuracyRow.mixedPrecision - accuracyRow.traditionalINT8)
    : '—';
  const latencyChange = latencyRow && latencyRow.traditionalINT8
    ? ((latencyRow.mixedPrecision - latencyRow.traditionalINT8) / latencyRow.traditionalINT8) * 100
    : 0;
  const memoryChange = memoryRow && memoryRow.traditionalINT8
    ? ((memoryRow.mixedPrecision - memoryRow.traditionalINT8) / memoryRow.traditionalINT8) * 100
    : 0;
  const powerChange = powerRadar && powerRadar.traditional
    ? ((powerRadar.mixedPrecision - powerRadar.traditional) / powerRadar.traditional) * 100
    : 0;

  return (
    <div className="max-w-7xl mx-auto">
      <motion.div
        initial={{ opacity: 0, y: -20 }}
        animate={{ opacity: 1, y: 0 }}
        className="mb-8"
      >
        <h1 className="text-3xl md:text-4xl font-bold text-slate-800 dark:text-white mb-2">
          量化效果对比
        </h1>
        <p className="text-slate-500 dark:text-slate-400">
          选择部署记录，对比传统全 INT8 量化与混合精度量化方案的性能差异
        </p>
      </motion.div>

      {/* Deployment Selector */}
      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        className="mb-8"
      >
        <Card>
          <div className="flex items-center gap-4">
            <Target className="w-5 h-5 text-slate-600 dark:text-slate-400" />
            <div className="flex-1">
              <Select
                value={selectedDeploymentId}
                onValueChange={setSelectedDeploymentId}
                options={deploymentOptions}
                placeholder={deploymentOptions.length > 0 ? '选择要对比的部署记录...' : '暂无成功部署记录，请先进行部署'}
              />
            </div>
            {selectedDeploymentId && (
              <Badge variant="info">
                <Activity className="w-3 h-3 mr-1" />
                混合精度 vs 传统 INT8
              </Badge>
            )}
          </div>
          {comparison && (
            <p className="mt-3 text-xs text-slate-400 dark:text-slate-500">
              对比任务 {comparison.jobId?.slice(0, 8)}：混合方案 {comparison.mixedPrecisionLayers} 个 INT8 层 /
              共 {comparison.traditionalLayers} 层（基线为全部层 INT8）
            </p>
          )}
        </Card>
      </motion.div>

      {comparisonError && (
        <div className="mb-6 flex items-start gap-2 rounded-xl border border-amber-300/60 bg-amber-50 dark:border-amber-500/30 dark:bg-amber-500/10 px-4 py-3 text-sm text-amber-700 dark:text-amber-300">
          <AlertCircle className="w-4 h-4 mt-0.5 flex-shrink-0" />
          <span>对比数据加载失败：{comparisonError}</span>
        </div>
      )}

      {/* No deployment message */}
      {deploymentOptions.length === 0 && (
        <Card className="text-center py-12">
          <BarChart3 className="w-16 h-16 mx-auto mb-4 text-slate-300 dark:text-slate-600" />
          <h3 className="text-lg font-semibold text-slate-700 dark:text-slate-300 mb-2">
            暂无部署数据
          </h3>
          <p className="text-slate-500 dark:text-slate-400">
            请先完成一次模型部署（部署成功后自动采集性能指标），再返回查看效果对比
          </p>
        </Card>
      )}

      {deploymentOptions.length > 0 && comparisonLoading && radarData.length === 0 && (
        <Card className="flex items-center justify-center gap-2 py-10 text-slate-500 dark:text-slate-400 mb-8">
          <Loader2 className="w-4 h-4 animate-spin" />
          正在计算对比数据...
        </Card>
      )}

      {deploymentOptions.length > 0 && comparisonData.length > 0 && (
        <>
          {/* Improvement Cards */}
          <motion.div
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: 0.1 }}
            className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-8"
          >
            <Card className="text-center">
              <Award className="w-7 h-7 mx-auto mb-2 text-slate-600 dark:text-slate-400" />
              <p className="text-3xl font-bold text-slate-800 dark:text-white">{accuracyImprovement}pp</p>
              <p className="text-sm text-slate-500 dark:text-slate-400">精度变化</p>
            </Card>
            <Card className="text-center">
              <Clock className="w-7 h-7 mx-auto mb-2 text-slate-600 dark:text-slate-400" />
              <p className="text-3xl font-bold text-slate-800 dark:text-white">{signed(latencyChange)}%</p>
              <p className="text-sm text-slate-500 dark:text-slate-400">延迟变化</p>
            </Card>
            <Card className="text-center">
              <HardDrive className="w-7 h-7 mx-auto mb-2 text-slate-600 dark:text-slate-400" />
              <p className="text-3xl font-bold text-slate-800 dark:text-white">{signed(memoryChange)}%</p>
              <p className="text-sm text-slate-500 dark:text-slate-400">内存变化</p>
            </Card>
            <Card className="text-center">
              <Zap className="w-7 h-7 mx-auto mb-2 text-slate-600 dark:text-slate-400" />
              <p className="text-3xl font-bold text-slate-800 dark:text-white">{signed(powerChange)}%</p>
              <p className="text-sm text-slate-500 dark:text-slate-400">功耗变化</p>
            </Card>
          </motion.div>

          {/* Charts */}
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-8 mb-8">
            <motion.div
              initial={{ opacity: 0, x: -20 }}
              animate={{ opacity: 1, x: 0 }}
              transition={{ delay: 0.2 }}
            >
              <Card>
                <h2 className="text-lg font-bold text-slate-900 dark:text-white mb-6 flex items-center gap-2">
                  <TrendingUp className="w-5 h-5 text-slate-700 dark:text-slate-200" />
                  性能雷达图
                </h2>
                <div className="h-[350px]">
                  <ResponsiveContainer width="100%" height="100%">
                    <RadarChart data={radarData}>
                      <PolarGrid stroke={theme === 'dark' ? '#4b5563' : '#e5e7eb'} />
                      <PolarAngleAxis
                        dataKey="metric"
                        tick={{ fill: theme === 'dark' ? '#d1d5db' : '#374151', fontSize: 14 }}
                      />
                      <PolarRadiusAxis
                        angle={30}
                        domain={[0, 100]}
                        tick={{ fill: theme === 'dark' ? '#9ca3af' : '#6b7280', fontSize: 12 }}
                      />
                      <Radar
                        name="传统 INT8"
                        dataKey="traditional"
                        stroke="#78716c"
                        fill="#78716c"
                        fillOpacity={0.2}
                        strokeWidth={2}
                      />
                      <Radar
                        name="混合精度"
                        dataKey="mixedPrecision"
                        stroke="#0ea5e9"
                        fill="#0ea5e9"
                        fillOpacity={0.3}
                        strokeWidth={2}
                      />
                      <Legend
                        wrapperStyle={{ paddingTop: '20px' }}
                        formatter={(value) => <span className="text-slate-700 dark:text-slate-200">{value}</span>}
                      />
                      <Tooltip
                        contentStyle={{
                          backgroundColor: 'rgba(255, 255, 255, 0.98)',
                          border: '1px solid #e5e7eb',
                          borderRadius: '8px',
                          color: '#1f2937',
                        }}
                      />
                    </RadarChart>
                  </ResponsiveContainer>
                </div>
              </Card>
            </motion.div>

            <motion.div
              initial={{ opacity: 0, x: 20 }}
              animate={{ opacity: 1, x: 0 }}
              transition={{ delay: 0.3 }}
            >
              <Card>
                <h2 className="text-lg font-bold text-slate-900 dark:text-white mb-6 flex items-center gap-2">
                  <BarChart3 className="w-5 h-5 text-slate-700 dark:text-slate-200" />
                  指标对比柱状图
                </h2>
                <div className="h-[350px]">
                  <ResponsiveContainer width="100%" height="100%">
                    <BarChart
                      data={comparisonData}
                      layout="vertical"
                      margin={{ top: 5, right: 30, left: 100, bottom: 5 }}
                    >
                      <CartesianGrid strokeDasharray="3 3" stroke={theme === 'dark' ? '#4b5563' : '#e5e7eb'} horizontal={false} />
                      <XAxis
                        type="number"
                        tick={{ fill: theme === 'dark' ? '#d1d5db' : '#374151' }}
                        axisLine={{ stroke: theme === 'dark' ? '#4b5563' : '#e5e7eb' }}
                      />
                      <YAxis
                        dataKey="metric"
                        type="category"
                        tick={{ fill: theme === 'dark' ? '#d1d5db' : '#374151', fontSize: 12 }}
                        axisLine={{ stroke: theme === 'dark' ? '#4b5563' : '#e5e7eb' }}
                        width={95}
                      />
                      <Tooltip
                        contentStyle={{
                          backgroundColor: 'rgba(255, 255, 255, 0.98)',
                          border: '1px solid #e5e7eb',
                          borderRadius: '8px',
                          color: '#1f2937',
                        }}
                      />
                      <Legend
                        wrapperStyle={{ paddingTop: '20px' }}
                        formatter={(value) => <span className="text-slate-700 dark:text-slate-200">{value}</span>}
                      />
                      <Bar
                        dataKey="traditionalINT8"
                        name="传统 INT8"
                        fill="#78716c"
                        radius={[0, 4, 4, 0]}
                        barSize={20}
                      />
                      <Bar
                        dataKey="mixedPrecision"
                        name="混合精度"
                        fill="#0ea5e9"
                        radius={[0, 4, 4, 0]}
                        barSize={20}
                      />
                    </BarChart>
                  </ResponsiveContainer>
                </div>
              </Card>
            </motion.div>
          </div>

          {/* Detailed Comparison Table */}
          <motion.div
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: 0.4 }}
          >
            <Card>
              <h2 className="text-lg font-bold text-slate-800 dark:text-white mb-6 flex items-center gap-2">
                <GitCompare className="w-5 h-5 text-slate-600 dark:text-slate-400" />
                详细指标对比
              </h2>
              <div className="overflow-x-auto">
                <table className="w-full">
                  <thead>
                    <tr className="border-b border-slate-200 dark:border-dark-700">
                      <th className="text-center py-3 px-4 text-slate-500 dark:text-slate-400 font-semibold">指标</th>
                      <th className="text-center py-3 px-4 text-slate-500 dark:text-slate-400 font-semibold">传统全 INT8</th>
                      <th className="text-center py-3 px-4 text-slate-800 dark:text-white font-semibold">混合精度</th>
                      <th className="text-center py-3 px-4 text-slate-500 dark:text-slate-400 font-semibold">差异</th>
                    </tr>
                  </thead>
                  <tbody>
                    {comparisonData.map((row, index) => {
                      const diff = row.mixedPrecision - row.traditionalINT8;
                      const percentDiff = row.traditionalINT8
                        ? ((diff / row.traditionalINT8) * 100).toFixed(1)
                        : '—';

                      const isBetter = row.metric.includes('延迟') || row.metric.includes('大小')
                        || row.metric.includes('占用') || row.metric.includes('功耗')
                        ? diff < 0
                        : diff > 0;

                      return (
                        <motion.tr
                          key={row.metric}
                          initial={{ opacity: 0, x: -10 }}
                          animate={{ opacity: 1, x: 0 }}
                          transition={{ delay: index * 0.05 }}
                          className="border-b border-slate-100 dark:border-dark-800 hover:bg-slate-50 dark:hover:bg-dark-800/50"
                        >
                          <td className="text-center py-4 px-4 text-slate-800 dark:text-white font-semibold">{row.metric}</td>
                          <td className="text-center py-4 px-4 text-slate-500 dark:text-slate-400">
                            {row.traditionalINT8.toFixed(1)}{row.unit}
                          </td>
                          <td className="text-center py-4 px-4 text-slate-800 dark:text-white font-bold">
                            {row.mixedPrecision.toFixed(1)}{row.unit}
                          </td>
                          <td className="text-center py-4 px-4">
                            <Badge variant={isBetter ? 'success' : 'error'}>
                              {isBetter ? '↑' : '↓'} {Math.abs(diff).toFixed(1)}{row.unit}（{Math.abs(parseFloat(percentDiff)) || 0}%）
                            </Badge>
                          </td>
                        </motion.tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            </Card>
          </motion.div>

          {/* Summary */}
          <motion.div
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: 0.5 }}
            className="mt-8"
          >
            <Card className="bg-slate-800 dark:bg-slate-900 border border-slate-700 dark:border-slate-800">
              <div className="flex items-start gap-4">
                <div className="w-10 h-10 rounded-lg bg-slate-700 dark:bg-slate-800 flex items-center justify-center flex-shrink-0">
                  <Award className="w-5 h-5 text-white dark:text-slate-300" />
                </div>
                <div>
                  <h3 className="text-lg font-bold text-slate-800 dark:text-white mb-2">量化方案结论</h3>
                  <p className="text-slate-600 dark:text-slate-300 leading-relaxed">
                    相对「全部层 INT8」基线，本方案将敏感层保留为
                    <span className="text-amber-600 dark:text-amber-400 font-semibold"> FP16</span>，
                    精度变化 <span className="text-slate-800 dark:text-white font-semibold">{accuracyImprovement}pp</span>，
                    推理延迟变化 <span className="text-slate-800 dark:text-white font-semibold">{signed(latencyChange)}%</span>，
                    内存变化 <span className="text-slate-800 dark:text-white font-semibold">{signed(memoryChange)}%</span>。
                    切换不同的部署记录可查看对应方案的对比数据。
                  </p>
                  {comparison?.rows?.length ? null : (
                    <p className="text-slate-500 dark:text-slate-400 text-sm mt-2">
                      提示：对比数据由后端基于该方案的层位宽重新计算，与部署时采集的指标口径一致。
                    </p>
                  )}
                </div>
              </div>
            </Card>
          </motion.div>
        </>
      )}
    </div>
  );
};
