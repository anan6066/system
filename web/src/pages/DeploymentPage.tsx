import React, { useEffect, useMemo, useRef, useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  Rocket,
  Cpu,
  Zap,
  Clock,
  CheckCircle,
  XCircle,
  AlertCircle,
  RotateCcw,
  Activity,
  HardDrive,
  Gauge,
  FileText,
  Calendar,
  Monitor,
  Loader2,
  Trash2,
} from 'lucide-react';
import { Card, Button, Select, Badge, Dialog, Input } from '../components/ui';
import { useAppStore } from '../store/appStore';
import { errorMessage } from '../api';
import { deploymentStatusMeta, formatDateTime, npuLabel } from '../utils/format';
import type { DeploymentLog } from '../types';

const getLogIcon = (type: string) => {
  switch (type) {
    case 'success': return <CheckCircle className="w-4 h-4 text-emerald-500" />;
    case 'error': return <XCircle className="w-4 h-4 text-red-500" />;
    case 'warning': return <AlertCircle className="w-4 h-4 text-amber-500" />;
    default: return <Activity className="w-4 h-4 text-slate-400" />;
  }
};

const logTextColor = (type: string) => {
  switch (type) {
    case 'error': return 'text-red-500';
    case 'success': return 'text-emerald-500';
    case 'warning': return 'text-amber-500';
    default: return 'text-slate-700 dark:text-slate-300';
  }
};

export const DeploymentPage: React.FC = () => {
  const {
    models,
    devices,
    deployments,
    fetchModels,
    fetchDevices,
    fetchDeployments,
    createDeployment,
    refreshDeployment,
    retryDeployment,
    deleteDeployment,
  } = useAppStore();

  const [selectedModel, setSelectedModel] = useState('');
  const [selectedDevice, setSelectedDevice] = useState('');
  const [targetDir, setTargetDir] = useState('');
  const [currentDeploymentId, setCurrentDeploymentId] = useState<string | null>(null);
  const [selectedDeployId, setSelectedDeployId] = useState<string | null>(null);
  const [deploying, setDeploying] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const finishedRef = useRef<string | null>(null);

  useEffect(() => {
    void fetchModels();
    void fetchDevices();
    void fetchDeployments();
  }, [fetchModels, fetchDevices, fetchDeployments]);

  const currentDeployment = useMemo(
    () => deployments.find((item) => item.id === currentDeploymentId) ?? null,
    [deployments, currentDeploymentId],
  );
  const selectedDeploy = useMemo(
    () => deployments.find((item) => item.id === selectedDeployId) ?? null,
    [deployments, selectedDeployId],
  );

  const isRunning =
    currentDeployment?.status === 'pending' || currentDeployment?.status === 'deploying';

  // 部署进行中：1s 轮询后端部署记录（日志/进度/指标一起刷新）
  useEffect(() => {
    if (!currentDeployment || !isRunning) return;
    const timer = window.setInterval(() => {
      void refreshDeployment(currentDeployment.id).catch(() => undefined);
    }, 1000);
    return () => window.clearInterval(timer);
  }, [currentDeployment, isRunning, refreshDeployment]);

  // 部署结束后：设备状态（busy→online）与首页统计都要重新拉一次
  useEffect(() => {
    if (!currentDeployment) return;
    if (currentDeployment.status !== 'success' && currentDeployment.status !== 'failed') return;
    if (finishedRef.current === currentDeployment.id) return;
    finishedRef.current = currentDeployment.id;
    void fetchDevices();
  }, [currentDeployment, fetchDevices]);

  const completedModels = models.filter((item) => item.status === 'completed');
  const onlineDevices = devices.filter((item) => item.status !== 'offline');

  const modelOptions = completedModels.map((item) => ({
    value: item.id,
    label: item.name,
    description: `NPU: ${npuLabel(item.targetNPU)} - ${item.quantizationLayers.length} 层`,
  }));

  const deviceOptions = onlineDevices.map((item) => ({
    value: item.id,
    label: item.name,
    description: `${item.ip} - ${item.status === 'online' ? '在线' : '忙碌'}`,
  }));

  const handleDeploy = async () => {
    if (!selectedModel || !selectedDevice) return;
    setError(null);
    setDeploying(true);
    try {
      const created = await createDeployment({
        modelId: selectedModel,
        deviceId: selectedDevice,
        ...(targetDir.trim() ? { targetDir: targetDir.trim() } : {}),
      });
      finishedRef.current = null;
      setCurrentDeploymentId(created.id);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setDeploying(false);
    }
  };

  const handleRetry = async (deploymentId: string) => {
    setError(null);
    try {
      await retryDeployment(deploymentId);
      finishedRef.current = null;
      setCurrentDeploymentId(deploymentId);
      setSelectedDeployId(null);
    } catch (err) {
      setError(errorMessage(err));
    }
  };

  const handleDelete = async (deploymentId: string) => {
    setError(null);
    try {
      await deleteDeployment(deploymentId);
      if (currentDeploymentId === deploymentId) setCurrentDeploymentId(null);
      setSelectedDeployId(null);
    } catch (err) {
      setError(errorMessage(err));
    }
  };

  const renderLogs = (logs: DeploymentLog[], emptyHint: string) => (
    <div className="bg-slate-50 dark:bg-dark-800/50 rounded-xl p-4 space-y-2 overflow-y-auto h-full">
      <AnimatePresence initial={false}>
        {logs.map((log, index) => (
          <motion.div
            key={`${log.id}-${index}`}
            initial={{ opacity: 0, x: -10 }}
            animate={{ opacity: 1, x: 0 }}
            className="flex items-start gap-3"
          >
            {getLogIcon(log.type)}
            <div className="flex-1">
              <span className="text-slate-400 text-xs mr-2">{log.timestamp}</span>
              <span className={`text-sm ${logTextColor(log.type)}`}>{log.message}</span>
            </div>
          </motion.div>
        ))}
      </AnimatePresence>
      {logs.length === 0 && (
        <div className="flex flex-col items-center justify-center h-full text-center">
          <Rocket className="w-16 h-16 text-slate-200 dark:text-slate-700 mb-4" />
          <p className="text-slate-400 dark:text-slate-500">{emptyHint}</p>
        </div>
      )}
    </div>
  );

  return (
    <div className="max-w-7xl mx-auto">
      <motion.div
        initial={{ opacity: 0, y: -20 }}
        animate={{ opacity: 1, y: 0 }}
        className="mb-8"
      >
        <h1 className="text-3xl md:text-4xl font-bold text-slate-800 dark:text-white mb-2">
          一键部署与数据采集
        </h1>
        <p className="text-slate-500 dark:text-slate-400">
          选择量化模型和目标设备，一键推送并自动采集推理性能数据
        </p>
      </motion.div>

      {error && (
        <div className="mb-6 flex items-start gap-2 rounded-xl border border-red-300/60 bg-red-50 dark:border-red-500/30 dark:bg-red-500/10 px-4 py-3 text-sm text-red-700 dark:text-red-300">
          <AlertCircle className="w-4 h-4 mt-0.5 flex-shrink-0" />
          <span className="flex-1">{error}</span>
          <button className="text-xs underline" onClick={() => setError(null)}>关闭</button>
        </div>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-8">
        <motion.div
          initial={{ opacity: 0, x: -20 }}
          animate={{ opacity: 1, x: 0 }}
          transition={{ delay: 0.1 }}
          className="lg:col-span-1"
        >
          <Card>
            <h2 className="text-lg font-bold text-slate-800 dark:text-white mb-6 flex items-center gap-2">
              <Rocket className="w-5 h-5 text-slate-600 dark:text-slate-400" />
              部署配置
            </h2>

            <div className="space-y-4">
              <Select
                label="选择量化模型"
                value={selectedModel}
                onValueChange={setSelectedModel}
                options={modelOptions}
                placeholder={completedModels.length ? '请选择已量化的模型...' : '暂无已量化模型'}
              />

              <Select
                label="选择目标设备"
                value={selectedDevice}
                onValueChange={setSelectedDevice}
                options={deviceOptions}
                placeholder={onlineDevices.length ? '请选择在线的 NPU 设备...' : '暂无在线设备'}
              />

              <Input
                label="目标目录（可选）"
                placeholder="默认 /data/models"
                value={targetDir}
                onChange={(e) => setTargetDir(e.target.value)}
              />

              <Button
                onClick={() => void handleDeploy()}
                disabled={deploying || isRunning || !selectedModel || !selectedDevice}
                loading={deploying || Boolean(isRunning)}
                className="w-full py-3 mt-4"
                icon={<Zap className="w-4 h-4" />}
              >
                {isRunning ? '部署中...' : '一键部署'}
              </Button>

              {completedModels.length === 0 && (
                <p className="text-xs text-slate-400 dark:text-slate-500">
                  还没有可部署的模型，请先到「模型量化」完成一次量化
                </p>
              )}
              {completedModels.length > 0 && onlineDevices.length === 0 && (
                <p className="text-xs text-amber-600 dark:text-amber-400">
                  设备列表中还没有在线设备，请先到「设备管理」添加并检测
                </p>
              )}
            </div>
          </Card>

          <Card className="mt-6">
            <h3 className="text-sm font-semibold text-slate-500 dark:text-slate-400 mb-4">可用资源</h3>
            <div className="space-y-3">
              <div className="flex items-center justify-between">
                <span className="text-slate-700 dark:text-slate-300">可部署模型</span>
                <span className="text-slate-800 dark:text-white font-bold">{completedModels.length}</span>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-slate-700 dark:text-slate-300">在线设备</span>
                <span className="text-emerald-600 dark:text-emerald-400 font-bold">{onlineDevices.length}</span>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-slate-700 dark:text-slate-300">总部署次数</span>
                <span className="text-slate-800 dark:text-white font-bold">{deployments.length}</span>
              </div>
            </div>
          </Card>
        </motion.div>

        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.2 }}
          className="lg:col-span-2"
        >
          <Card className="min-h-[500px]">
            <div className="flex items-center justify-between mb-6">
              <h2 className="text-lg font-bold text-slate-800 dark:text-white flex items-center gap-2">
                <Activity className="w-5 h-5 text-slate-600 dark:text-slate-400" />
                部署日志
              </h2>
              {currentDeployment && (
                <Badge variant={deploymentStatusMeta(currentDeployment.status).badge}>
                  {currentDeployment.status === 'deploying' && (
                    <RotateCcw className="w-3 h-3 mr-1 animate-spin" />
                  )}
                  {currentDeployment.status === 'pending' && <Clock className="w-3 h-3 mr-1" />}
                  {deploymentStatusMeta(currentDeployment.status).text}
                </Badge>
              )}
            </div>

            <div className="h-[350px]">
              {currentDeployment ? (
                renderLogs(currentDeployment.logs, '等待后端推送日志...')
              ) : (
                <div className="flex flex-col items-center justify-center h-full text-center bg-slate-50 dark:bg-dark-800/50 rounded-xl">
                  <Rocket className="w-16 h-16 text-slate-200 dark:text-slate-700 mb-4" />
                  <p className="text-slate-400 dark:text-slate-500">选择模型和设备，开始部署</p>
                </div>
              )}
            </div>

            {currentDeployment?.status === 'failed' && currentDeployment.error && (
              <div className="mt-4 flex items-start justify-between gap-3 rounded-xl border border-red-300/60 bg-red-50 dark:border-red-500/30 dark:bg-red-500/10 px-4 py-3 text-sm text-red-700 dark:text-red-300">
                <span>部署失败：{currentDeployment.error}</span>
                <Button
                  variant="secondary"
                  size="sm"
                  onClick={() => void handleRetry(currentDeployment.id)}
                  icon={<RotateCcw className="w-3.5 h-3.5" />}
                >
                  重试
                </Button>
              </div>
            )}

            {currentDeployment?.metrics && (
              <motion.div
                initial={{ opacity: 0, y: 20 }}
                animate={{ opacity: 1, y: 0 }}
                className="mt-6"
              >
                <div className="flex items-center justify-between mb-3">
                  <h3 className="text-sm font-semibold text-slate-500 dark:text-slate-400">性能指标</h3>
                  <Badge variant={currentDeployment.metricsSource === 'measured' ? 'success' : 'warning'}>
                    {currentDeployment.metricsSource === 'measured' ? '开发板实测' : '按方案估算'}
                  </Badge>
                </div>
                <div className="grid grid-cols-3 gap-4">
                  <div className="bg-slate-100 dark:bg-dark-800 rounded-xl p-4 text-center">
                    <Gauge className="w-6 h-6 mx-auto mb-2 text-slate-600 dark:text-slate-400" />
                    <p className="text-2xl font-bold text-slate-800 dark:text-white">
                      {currentDeployment.metrics.inferenceSpeed.toFixed(1)}ms
                    </p>
                    <p className="text-sm text-slate-500 dark:text-slate-400">推理延迟</p>
                  </div>
                  <div className="bg-slate-100 dark:bg-dark-800 rounded-xl p-4 text-center">
                    <HardDrive className="w-6 h-6 mx-auto mb-2 text-slate-600 dark:text-slate-400" />
                    <p className="text-2xl font-bold text-slate-800 dark:text-white">
                      {Math.round(currentDeployment.metrics.memoryUsage)}MB
                    </p>
                    <p className="text-sm text-slate-500 dark:text-slate-400">内存占用</p>
                  </div>
                  <div className="bg-slate-100 dark:bg-dark-800 rounded-xl p-4 text-center">
                    <Cpu className="w-6 h-6 mx-auto mb-2 text-slate-600 dark:text-slate-400" />
                    <p className="text-2xl font-bold text-slate-800 dark:text-white">
                      {currentDeployment.metrics.top1Accuracy.toFixed(1)}%
                    </p>
                    <p className="text-sm text-slate-500 dark:text-slate-400">Top-1 准确率</p>
                  </div>
                </div>
              </motion.div>
            )}
          </Card>
        </motion.div>
      </div>

      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.3 }}
        className="mt-8"
      >
        <h2 className="text-xl font-bold text-slate-800 dark:text-white mb-4">部署历史</h2>
        <div className="space-y-3">
          {deployments.length === 0 && (
            <Card variant="bordered" className="border-dashed text-center py-8">
              <p className="text-slate-500 dark:text-slate-400">还没有部署记录</p>
            </Card>
          )}
          {deployments.slice(0, 10).map((deploy) => (
            <motion.div
              key={deploy.id}
              initial={{ opacity: 0, x: -10 }}
              animate={{ opacity: 1, x: 0 }}
            >
              <Card
                hover
                className="py-4 cursor-pointer"
                onClick={() => setSelectedDeployId(deploy.id)}
              >
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-4">
                    <Badge variant={deploymentStatusMeta(deploy.status).badge}>
                      {deploymentStatusMeta(deploy.status).text}
                    </Badge>
                    <div>
                      <p className="text-slate-800 dark:text-white font-semibold">
                        {deploy.modelName ?? '未知模型'}
                      </p>
                      <p className="text-sm text-slate-500 dark:text-slate-400">
                        部署到 {deploy.deviceName ?? '未知设备'}
                      </p>
                    </div>
                  </div>
                  <div className="flex items-center gap-4">
                    <div className="text-right">
                      <p className="text-sm text-slate-500 dark:text-slate-400">
                        {formatDateTime(deploy.startTime)}
                      </p>
                      {deploy.metrics && (
                        <div className="flex gap-4 mt-1 text-xs">
                          <span className="text-slate-600 dark:text-slate-400">
                            {deploy.metrics.inferenceSpeed.toFixed(1)}ms
                          </span>
                          <span className="text-slate-600 dark:text-slate-400">
                            {Math.round(deploy.metrics.memoryUsage)}MB
                          </span>
                          <span className="text-slate-600 dark:text-slate-400">
                            {deploy.metrics.top1Accuracy.toFixed(1)}%
                          </span>
                        </div>
                      )}
                    </div>
                    <FileText className="w-5 h-5 text-slate-400" />
                  </div>
                </div>
              </Card>
            </motion.div>
          ))}
        </div>
      </motion.div>

      {/* Deployment Detail Dialog */}
      <Dialog
        open={Boolean(selectedDeploy)}
        onOpenChange={() => setSelectedDeployId(null)}
        title="部署报告详情"
        description={selectedDeploy ? `模型：${selectedDeploy.modelName ?? '—'}` : ''}
      >
        {selectedDeploy && (
          <div className="space-y-6">
            <div className="grid grid-cols-2 gap-4">
              <div className="bg-slate-50 dark:bg-dark-800 rounded-xl p-4">
                <div className="flex items-center gap-2 mb-2">
                  <Calendar className="w-4 h-4 text-slate-400" />
                  <span className="text-sm text-slate-500">部署时间</span>
                </div>
                <p className="text-slate-800 dark:text-white font-semibold">
                  {formatDateTime(selectedDeploy.startTime)}
                </p>
              </div>
              <div className="bg-slate-50 dark:bg-dark-800 rounded-xl p-4">
                <div className="flex items-center gap-2 mb-2">
                  <Monitor className="w-4 h-4 text-slate-400" />
                  <span className="text-sm text-slate-500">目标设备</span>
                </div>
                <p className="text-slate-800 dark:text-white font-semibold">
                  {selectedDeploy.deviceName ?? '—'}
                </p>
              </div>
              <div className="bg-slate-50 dark:bg-dark-800 rounded-xl p-4">
                <div className="flex items-center gap-2 mb-2">
                  <HardDrive className="w-4 h-4 text-slate-400" />
                  <span className="text-sm text-slate-500">推送目录</span>
                </div>
                <p className="text-slate-800 dark:text-white font-semibold break-all">
                  {selectedDeploy.targetDir}
                </p>
              </div>
              <div className="bg-slate-50 dark:bg-dark-800 rounded-xl p-4">
                <div className="flex items-center gap-2 mb-2">
                  <Gauge className="w-4 h-4 text-slate-400" />
                  <span className="text-sm text-slate-500">部署状态</span>
                </div>
                <Badge variant={deploymentStatusMeta(selectedDeploy.status).badge}>
                  {deploymentStatusMeta(selectedDeploy.status).text}
                </Badge>
              </div>
            </div>

            {selectedDeploy.remoteFile && (
              <p className="text-xs text-slate-500 dark:text-slate-400">
                远端文件：<span className="font-mono">{selectedDeploy.remoteFile}</span>
              </p>
            )}

            {selectedDeploy.metrics && (
              <div>
                <div className="flex items-center justify-between mb-3">
                  <h4 className="text-sm font-semibold text-slate-700 dark:text-slate-300">性能指标</h4>
                  <Badge variant={selectedDeploy.metricsSource === 'measured' ? 'success' : 'warning'}>
                    {selectedDeploy.metricsSource === 'measured' ? '开发板实测' : '按方案估算'}
                  </Badge>
                </div>
                <div className="grid grid-cols-3 gap-4">
                  <div className="bg-slate-100 dark:bg-dark-800 rounded-xl p-4 text-center">
                    <p className="text-2xl font-bold text-slate-800 dark:text-white">
                      {selectedDeploy.metrics.inferenceSpeed.toFixed(1)}ms
                    </p>
                    <p className="text-xs text-slate-500 dark:text-slate-400">推理延迟</p>
                  </div>
                  <div className="bg-slate-100 dark:bg-dark-800 rounded-xl p-4 text-center">
                    <p className="text-2xl font-bold text-slate-800 dark:text-white">
                      {Math.round(selectedDeploy.metrics.memoryUsage)}MB
                    </p>
                    <p className="text-xs text-slate-500 dark:text-slate-400">内存占用</p>
                  </div>
                  <div className="bg-slate-100 dark:bg-dark-800 rounded-xl p-4 text-center">
                    <p className="text-2xl font-bold text-slate-800 dark:text-white">
                      {selectedDeploy.metrics.top1Accuracy.toFixed(1)}%
                    </p>
                    <p className="text-xs text-slate-500 dark:text-slate-400">Top-1 准确率</p>
                  </div>
                </div>
              </div>
            )}

            <div>
              <h4 className="text-sm font-semibold text-slate-700 dark:text-slate-300 mb-3">部署日志</h4>
              <div className="bg-slate-50 dark:bg-dark-800 rounded-xl p-4 max-h-48 overflow-y-auto space-y-2">
                {selectedDeploy.logs.map((log, index) => (
                  <div key={`${log.id}-${index}`} className="flex items-start gap-2 text-sm">
                    {getLogIcon(log.type)}
                    <span className="text-slate-400 text-xs mr-2 mt-0.5">{log.timestamp}</span>
                    <span className={logTextColor(log.type)}>{log.message}</span>
                  </div>
                ))}
                {selectedDeploy.logs.length === 0 && (
                  <p className="text-sm text-slate-400">暂无日志</p>
                )}
              </div>
            </div>

            {(() => {
              const model = models.find((item) => item.id === selectedDeploy.modelId);
              if (!model || model.quantizationLayers.length === 0) return null;
              return (
                <div>
                  <h4 className="text-sm font-semibold text-slate-700 dark:text-slate-300 mb-3">模型层信息</h4>
                  <div className="bg-slate-50 dark:bg-dark-800 rounded-xl p-4 space-y-3">
                    <div className="flex items-center justify-between">
                      <span className="text-sm text-slate-500">INT8 层</span>
                      <Badge variant="success">
                        {model.quantizationLayers.filter((layer) => layer.type === 'INT8').length} 层
                      </Badge>
                    </div>
                    <div className="flex items-center justify-between">
                      <span className="text-sm text-slate-500">FP16 层</span>
                      <Badge variant="warning">
                        {model.quantizationLayers.filter((layer) => layer.type === 'FP16').length} 层
                      </Badge>
                    </div>
                    <div className="flex items-center justify-between">
                      <span className="text-sm text-slate-500">压缩率</span>
                      <Badge variant="info">
                        {(() => {
                          const original = model.quantizationLayers.reduce((acc, layer) => acc + layer.originalSize, 0);
                          const quantized = model.quantizationLayers.reduce((acc, layer) => acc + layer.quantizedSize, 0);
                          return original ? `${Math.round((1 - quantized / original) * 100)}%` : '—';
                        })()}
                      </Badge>
                    </div>
                  </div>
                </div>
              );
            })()}

            <div className="flex gap-3 pt-2">
              {selectedDeploy.status === 'failed' && (
                <Button
                  variant="secondary"
                  className="flex-1"
                  onClick={() => void handleRetry(selectedDeploy.id)}
                  icon={<RotateCcw className="w-4 h-4" />}
                >
                  重新部署
                </Button>
              )}
              {selectedDeploy.status !== 'pending' && selectedDeploy.status !== 'deploying' && (
                <Button
                  variant="danger"
                  className="flex-1"
                  onClick={() => void handleDelete(selectedDeploy.id)}
                  icon={<Trash2 className="w-4 h-4" />}
                >
                  删除记录
                </Button>
              )}
              {isRunning && selectedDeploy.id === currentDeploymentId && (
                <div className="flex-1 flex items-center justify-center gap-2 text-sm text-slate-500">
                  <Loader2 className="w-4 h-4 animate-spin" />
                  部署进行中，暂不可操作
                </div>
              )}
            </div>
          </div>
        )}
      </Dialog>
    </div>
  );
};
