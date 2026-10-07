import React, { useCallback, useEffect, useRef, useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  Upload,
  Settings,
  Zap,
  Download,
  CheckCircle,
  Loader2,
  Sparkles,
  Layers,
  Check,
  FileText,
  CpuIcon,
  Gauge,
  CircleDot,
  FolderOpen,
  AlertCircle,
  Star,
  RotateCcw,
} from 'lucide-react';
import { Card, Button, Select, Badge, Progress } from '../components/ui';
import { useAppStore } from '../store/appStore';
import { errorMessage, jobsApi } from '../api';
import { jobStatusMeta, npuLabel, npuOptions, formatSizeKb } from '../utils/format';
import type { JobLogEntry, QuantizationJob, QuantizationLayer, QuantizationScheme } from '../types';

type QuantizationStep = 'config' | 'analyzing' | 'plan' | 'quantizing' | 'complete';

const STEPS: QuantizationStep[] = ['config', 'analyzing', 'plan', 'quantizing', 'complete'];
const POLL_INTERVAL_MS = 1200;

const getLayerTypeColor = (type: string) => {
  switch (type) {
    case 'INT8': return 'bg-slate-800 dark:bg-slate-200 text-white dark:text-slate-800 border-transparent';
    case 'FP16': return 'bg-white dark:bg-dark-800 text-slate-700 dark:text-slate-300 border-slate-300 dark:border-dark-600';
    default: return 'bg-slate-100 dark:bg-slate-500/20 text-slate-700 dark:text-slate-400 border-slate-200 dark:border-slate-500/30';
  }
};

export const QuantizationPage: React.FC = () => {
  const { presets, fetchPresets, uploadModel, createModelFromPreset, fetchModels } = useAppStore();

  // 配置
  const [modelType, setModelType] = useState<'preset' | 'custom'>('preset');
  const [selectedPreset, setSelectedPreset] = useState('');
  const [selectedNPU, setSelectedNPU] = useState('ascend');
  const [file, setFile] = useState<File | null>(null);
  const [fileName, setFileName] = useState('');
  const [datasetFile, setDatasetFile] = useState('');
  const datasetInputRef = useRef<HTMLInputElement>(null);

  // 任务
  const [step, setStep] = useState<QuantizationStep>('config');
  const [job, setJob] = useState<QuantizationJob | null>(null);
  const [schemes, setSchemes] = useState<QuantizationScheme[]>([]);
  const [schemeIndex, setSchemeIndex] = useState<number | null>(null);
  const [layers, setLayers] = useState<QuantizationLayer[]>([]);
  const [logs, setLogs] = useState<JobLogEntry[]>([]);

  // 交互状态
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [showExportSuccess, setShowExportSuccess] = useState(false);

  const pollRef = useRef<number | null>(null);
  const stageRef = useRef<string>('');

  useEffect(() => {
    void fetchPresets();
  }, [fetchPresets]);

  const stopPolling = useCallback(() => {
    if (pollRef.current !== null) {
      window.clearInterval(pollRef.current);
      pollRef.current = null;
    }
  }, []);

  useEffect(() => stopPolling, [stopPolling]);

  const loadSchemes = useCallback(async (readyJob: QuantizationJob) => {
    const list = await jobsApi.schemes(readyJob.id);
    setSchemes(list);
    const preferred =
      readyJob.selectedSchemeIndex ??
      list.find((item) => item.recommended)?.index ??
      list[0]?.index ??
      null;
    setSchemeIndex(preferred);
    setLayers(list.find((item) => item.index === preferred)?.layers ?? []);
  }, []);

  const onOmReady = useCallback(
    async (finishedJob: QuantizationJob) => {
      setLayers(await jobsApi.layers(finishedJob.id));
      // 模型状态已在后端置为 completed，刷新列表供部署页使用
      await fetchModels();
    },
    [fetchModels],
  );

  /** 轮询任务：驱动步骤条、进度、日志与节点动作。 */
  const startPolling = useCallback(
    (jobId: string) => {
      stopPolling();
      stageRef.current = '';

      const tick = async () => {
        try {
          const fresh = await jobsApi.get(jobId);
          setJob(fresh);
          setStep(jobStatusMeta(fresh.status).step);

          const marker = `${fresh.stage}:${fresh.progress}:${fresh.status}`;
          if (stageRef.current !== marker) {
            stageRef.current = marker;
            try {
              const entries = await jobsApi.logs(jobId);
              setLogs(entries.slice(-8));
            } catch {
              /* 日志拉取失败不影响主流程 */
            }
          }

          if (fresh.status === 'failed') {
            stopPolling();
            setError(fresh.error ?? '量化任务失败');
            return;
          }
          if (fresh.status === 'scheme_ready') {
            stopPolling();
            await loadSchemes(fresh);
            return;
          }
          if (fresh.status === 'om_ready' || fresh.status === 'deployed') {
            stopPolling();
            await onOmReady(fresh);
          }
        } catch (err) {
          stopPolling();
          setError(errorMessage(err));
        }
      };

      void tick();
      pollRef.current = window.setInterval(tick, POLL_INTERVAL_MS);
    },
    [loadSchemes, onOmReady, stopPolling],
  );

  /** ① 生成量化方案：准备模型 → 创建任务 → 等 ① HAWQ + ② NSGA-II */
  const generateQuantizationPlan = async () => {
    setError(null);
    setSchemes([]);
    setLayers([]);
    setLogs([]);
    setSchemeIndex(null);
    stageRef.current = '';

    if (modelType === 'preset' && !selectedPreset) {
      setError('请先选择预设模型');
      return;
    }
    if (modelType === 'custom' && !file) {
      setError('请先上传 .onnx 模型文件');
      return;
    }

    setBusy(true);
    setStep('analyzing');
    try {
      const model =
        modelType === 'preset'
          ? await createModelFromPreset(selectedPreset, { targetNPU: 'ascend' })
          : await uploadModel(file as File, { targetNPU: 'ascend' });

      const created = await jobsApi.create(model.id, 'ascend');
      setJob(created);
      startPolling(created.id);
    } catch (err) {
      setError(errorMessage(err));
      setStep('config');
    } finally {
      setBusy(false);
    }
  };

  /** ④⑤ 选定方案并执行量化 → 等 ATC 产出 .om */
  const executeQuantization = async () => {
    if (!job) return;
    setError(null);
    setBusy(true);
    setStep('quantizing');
    stopPolling();
    try {
      const started = await jobsApi.select(job.id, schemeIndex ?? undefined);
      setJob(started);
      startPolling(started.id);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  const handleCancel = async () => {
    if (!job) return;
    try {
      stopPolling();
      const canceled = await jobsApi.cancel(job.id);
      setJob(canceled);
      setStep('config');
      setError(canceled.error ?? '任务已取消');
    } catch (err) {
      setError(errorMessage(err));
    }
  };

  const handleExport = async () => {
    if (!job) return;
    try {
      // 下载是异步的（要带鉴权头取 blob），失败不能装作成功
      await jobsApi.downloadOm(job.id, `model_${job.id.slice(0, 8)}.om`);
      setError(null);
      setShowExportSuccess(true);
      window.setTimeout(() => setShowExportSuccess(false), 3000);
    } catch (err) {
      setError(errorMessage(err));
    }
  };

  const resetAll = () => {
    stopPolling();
    setJob(null);
    setSchemes([]);
    setLayers([]);
    setLogs([]);
    setSchemeIndex(null);
    setError(null);
    setStep('config');
  };

  const handleFileUpload = (e: React.ChangeEvent<HTMLInputElement>) => {
    const picked = e.target.files?.[0];
    if (!picked) return;
    if (!picked.name.toLowerCase().endsWith('.onnx')) {
      setError('仅支持 .onnx 模型文件');
      return;
    }
    setFile(picked);
    setFileName(picked.name);
    setError(null);
    resetAll();
  };

  const handleDatasetUpload = (e: React.ChangeEvent<HTMLInputElement>) => {
    const picked = e.target.files?.[0];
    if (picked) setDatasetFile(picked.name);
  };

  const presetOptions = presets.map((item) => ({
    value: item.id,
    label: item.name,
    description: `${item.description} - ${item.size} - ${item.layerCount} 层`,
  }));

  const statusMeta = job ? jobStatusMeta(job.status) : null;
  const hasPlan = step === 'plan' && schemes.length > 0;
  const quantizationComplete = step === 'complete' && layers.length > 0;
  const isRunning = step === 'analyzing' || step === 'quantizing';
  const analyzingNow =
    job != null && ['pending', 'sensitivity_analysis', 'scheme_search'].includes(job.status);
  const quantizingNow = job != null && (job.status === 'quantizing' || job.status === 'converting');
  const selectedScheme = schemes.find((item) => item.index === schemeIndex) ?? null;
  const canGenerate =
    modelType === 'preset' ? Boolean(selectedPreset) : Boolean(file);

  return (
    <div className="max-w-6xl mx-auto">
      <motion.div
        initial={{ opacity: 0, y: -20 }}
        animate={{ opacity: 1, y: 0 }}
        className="mb-8"
      >
        <h1 className="text-3xl md:text-4xl font-bold text-slate-800 dark:text-white mb-2">
          模型量化配置
        </h1>
        <p className="text-slate-500 dark:text-slate-400">
          上传自定义 ONNX 模型或选择预设模型，配置目标 NPU，生成混合精度量化方案
        </p>
      </motion.div>

      {error && (
        <div className="mb-6 flex items-start gap-2 rounded-xl border border-red-300/60 bg-red-50 dark:border-red-500/30 dark:bg-red-500/10 px-4 py-3 text-sm text-red-700 dark:text-red-300">
          <AlertCircle className="w-4 h-4 mt-0.5 flex-shrink-0" />
          <span className="flex-1">{error}</span>
          <button className="text-xs underline" onClick={() => setError(null)}>关闭</button>
        </div>
      )}

      {/* Progress Steps */}
      {step !== 'config' && (
        <motion.div
          initial={{ opacity: 0, y: -10 }}
          animate={{ opacity: 1, y: 0 }}
          className="mb-8"
        >
          <div className="flex items-center justify-center gap-2 mb-4">
            {STEPS.map((item, index) => {
              const currentIndex = STEPS.indexOf(step);
              const isActive = index === currentIndex;
              const isComplete = index < currentIndex;
              return (
                <React.Fragment key={item}>
                  <div className={`
                    flex items-center justify-center w-8 h-8 rounded-full text-sm font-medium
                    ${isComplete ? 'bg-slate-800 dark:bg-slate-200 text-white dark:text-slate-800' : ''}
                    ${isActive ? 'bg-slate-800 dark:bg-slate-200 text-white dark:text-slate-800 animate-pulse' : ''}
                    ${!isComplete && !isActive ? 'bg-slate-200 dark:bg-dark-700 text-slate-400' : ''}
                  `}>
                    {isComplete ? <Check className="w-4 h-4" /> : index + 1}
                  </div>
                  {index < STEPS.length - 1 && (
                    <div className={`w-12 h-0.5 ${isComplete ? 'bg-slate-800 dark:bg-slate-200' : 'bg-slate-200 dark:bg-dark-700'}`} />
                  )}
                </React.Fragment>
              );
            })}
          </div>
          <p className="text-center text-sm text-slate-600 dark:text-slate-400">
            {job?.message || '配置模型参数'}
            {job && isRunning ? `（${job.progress}%）` : ''}
          </p>
          {isRunning && (
            <div className="mt-2 flex justify-center">
              <Button variant="ghost" size="sm" onClick={() => void handleCancel()}>
                取消任务
              </Button>
            </div>
          )}
        </motion.div>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-8">
        {/* Left Column - Configuration */}
        <motion.div
          initial={{ opacity: 0, x: -20 }}
          animate={{ opacity: 1, x: 0 }}
          transition={{ delay: 0.1 }}
          className="space-y-6"
        >
          <Card>
            <h2 className="text-lg font-bold text-slate-800 dark:text-white mb-4 flex items-center gap-2">
              <FileText className="w-5 h-5 text-slate-600 dark:text-slate-400" />
              选择模型类型
            </h2>
            <div className="flex gap-3 mb-6">
              <button
                onClick={() => { setModelType('preset'); setFileName(''); setFile(null); resetAll(); }}
                disabled={isRunning}
                className={`
                  flex-1 py-3 px-4 rounded-xl font-semibold transition-all duration-200
                  ${modelType === 'preset'
                    ? 'bg-slate-800 dark:bg-slate-200 text-white dark:text-slate-800 shadow-lg'
                    : 'bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-300 hover:bg-slate-200 dark:hover:bg-dark-700'
                  }
                  disabled:opacity-50
                `}
              >
                预设模型
              </button>
              <button
                onClick={() => { setModelType('custom'); setSelectedPreset(''); resetAll(); }}
                disabled={isRunning}
                className={`
                  flex-1 py-3 px-4 rounded-xl font-semibold transition-all duration-200
                  ${modelType === 'custom'
                    ? 'bg-slate-800 dark:bg-slate-200 text-white dark:text-slate-800 shadow-lg'
                    : 'bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-300 hover:bg-slate-200 dark:hover:bg-dark-700'
                  }
                  disabled:opacity-50
                `}
              >
                自定义上传
              </button>
            </div>

            {modelType === 'preset' ? (
              <Select
                label="选择预设模型"
                value={selectedPreset}
                onValueChange={(val) => { setSelectedPreset(val); resetAll(); }}
                options={presetOptions}
                placeholder={presets.length ? '请选择预设模型...' : '正在加载预设模型...'}
              />
            ) : (
              <div className="space-y-4">
                <label className="block text-sm font-semibold text-slate-700 dark:text-slate-300 mb-2">
                  上传 ONNX 模型
                </label>
                <div className="relative">
                  <input
                    type="file"
                    accept=".onnx"
                    onChange={handleFileUpload}
                    disabled={isRunning}
                    className="absolute inset-0 w-full h-full opacity-0 cursor-pointer"
                  />
                  <div className={`
                    border-2 border-dashed rounded-xl p-8 text-center
                    transition-all duration-200
                    ${fileName
                      ? 'border-slate-800 dark:border-slate-200 bg-slate-50 dark:bg-dark-800'
                      : 'border-slate-300 dark:border-dark-600 hover:border-slate-400 dark:hover:border-slate-500'
                    }
                  `}>
                    <Upload className={`w-10 h-10 mx-auto mb-3 ${fileName ? 'text-slate-800 dark:text-slate-200' : 'text-slate-400'}`} />
                    {fileName ? (
                      <>
                        <p className="text-slate-800 dark:text-white font-semibold">{fileName}</p>
                        <p className="text-xs text-slate-500 dark:text-slate-400 mt-1">
                          {file ? `${(file.size / 1024 / 1024).toFixed(2)} MB` : ''}
                        </p>
                      </>
                    ) : (
                      <>
                        <p className="text-slate-700 dark:text-slate-300 mb-1 font-medium">点击或拖拽文件到此处上传</p>
                        <p className="text-slate-400 dark:text-slate-500 text-sm">支持 .onnx 格式，最大 500MB</p>
                      </>
                    )}
                  </div>
                </div>
              </div>
            )}
          </Card>

          <Card>
            <h2 className="text-lg font-bold text-slate-800 dark:text-white mb-4 flex items-center gap-2">
              <CpuIcon className="w-5 h-5 text-slate-600 dark:text-slate-400" />
              目标 NPU
            </h2>
            <Select
              value={selectedNPU}
              onValueChange={setSelectedNPU}
              options={npuOptions}
              placeholder="请选择目标 NPU..."
            />
          </Card>

          <Card variant="bordered">
            <input
              ref={datasetInputRef}
              type="file"
              accept=".json,.npy,.npz,.txt"
              onChange={handleDatasetUpload}
              className="hidden"
            />
            <div
              onClick={() => datasetInputRef.current?.click()}
              className="cursor-pointer"
            >
              <div className="flex items-center justify-between">
                <div>
                  <h3 className="font-semibold text-slate-700 dark:text-slate-300">校准数据集（预留）</h3>
                  <p className="text-sm text-slate-500 dark:text-slate-400 mt-1">
                    {datasetFile ? `已选择: ${datasetFile}` : '当前占位算法使用随机校准集，暂未消费上传的数据集'}
                  </p>
                </div>
                <div className={`w-10 h-10 rounded-lg flex items-center justify-center ${datasetFile ? 'bg-emerald-100 dark:bg-emerald-500/20' : 'bg-slate-100 dark:bg-slate-800'}`}>
                  {datasetFile ? (
                    <CheckCircle className="w-5 h-5 text-emerald-500" />
                  ) : (
                    <FolderOpen className="w-5 h-5 text-slate-400" />
                  )}
                </div>
              </div>
            </div>
          </Card>

          {!hasPlan && !quantizationComplete && (
            <Button
              onClick={() => void generateQuantizationPlan()}
              disabled={busy || isRunning || !canGenerate}
              loading={analyzingNow || (busy && step === 'analyzing')}
              className="w-full py-4 text-lg"
              icon={<Zap className="w-5 h-5" />}
            >
              {analyzingNow || (busy && step === 'analyzing') ? '分析中...' : '生成量化方案'}
            </Button>
          )}

          {hasPlan && !quantizationComplete && (
            <Button
              onClick={() => void executeQuantization()}
              disabled={busy || isRunning || schemeIndex === null}
              loading={quantizingNow}
              className="w-full py-4 text-lg"
              icon={<Gauge className="w-5 h-5" />}
            >
              {quantizingNow
                ? '量化中...'
                : `开始量化${schemeIndex !== null ? `（方案 #${schemeIndex}）` : ''}`}
            </Button>
          )}

          {(isRunning || job) && (
            <Card>
              <div className="space-y-3">
                <div className="flex justify-between text-sm">
                  <span className="text-slate-600 dark:text-slate-400">
                    {statusMeta?.text ?? '任务进度'}
                    {job ? `（${job.id.slice(0, 8)}）` : ''}
                  </span>
                  <span className="font-semibold text-slate-800 dark:text-white">
                    {job?.progress ?? 0}%
                  </span>
                </div>
                <Progress value={job?.progress ?? 0} max={100} />
                {logs.length > 0 && (
                  <div className="mt-2 max-h-32 overflow-y-auto rounded-lg bg-slate-50 dark:bg-dark-800/50 p-3 space-y-1">
                    {logs.map((entry) => (
                      <p key={entry.id} className="text-xs font-mono text-slate-500 dark:text-slate-400">
                        [{entry.percent}%] {entry.message}
                      </p>
                    ))}
                  </div>
                )}
                {job && (job.status === 'om_ready' || job.status === 'deployed') && (
                  <Button variant="secondary" size="sm" className="w-full" onClick={resetAll} icon={<RotateCcw className="w-3.5 h-3.5" />}>
                    重新配置
                  </Button>
                )}
              </div>
            </Card>
          )}
        </motion.div>

        {/* Right Column - Results */}
        <motion.div
          initial={{ opacity: 0, x: 20 }}
          animate={{ opacity: 1, x: 0 }}
          transition={{ delay: 0.2 }}
          className="space-y-6"
        >
          {/* 帕累托前沿：等后端跑完 ② NSGA-II 后展示，由用户选一个方案 */}
          {hasPlan && !quantizationComplete && (
            <motion.div initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }}>
              <Card className="border-slate-800 dark:border-slate-200">
                <div className="flex items-center justify-between mb-6">
                  <h2 className="text-lg font-bold text-slate-800 dark:text-white flex items-center gap-2">
                    <Sparkles className="w-5 h-5 text-slate-600 dark:text-slate-400" />
                    帕累托前沿（{schemes.length} 个方案）
                  </h2>
                  <Badge variant="default">
                    <CircleDot className="w-3 h-3 mr-1" />
                    待执行
                  </Badge>
                </div>

                <div className="space-y-2 mb-6 max-h-72 overflow-y-auto pr-1">
                  {schemes.map((scheme) => {
                    const active = scheme.index === schemeIndex;
                    return (
                      <button
                        key={scheme.index}
                        type="button"
                        onClick={() => { setSchemeIndex(scheme.index); setLayers(scheme.layers); }}
                        className={`
                          w-full text-left rounded-xl border px-4 py-3 transition-all
                          ${active
                            ? 'border-slate-800 dark:border-slate-200 bg-slate-50 dark:bg-dark-800'
                            : 'border-slate-200 dark:border-dark-700 hover:border-slate-400 dark:hover:border-dark-500'
                          }
                        `}
                      >
                        <div className="flex items-center justify-between mb-2">
                          <span className="font-semibold text-slate-800 dark:text-white">
                            方案 #{scheme.index}
                          </span>
                          <div className="flex items-center gap-2">
                            {scheme.recommended && (
                              <Badge variant="success">
                                <Star className="w-3 h-3 mr-1" />
                                推荐
                              </Badge>
                            )}
                            {active && <Badge variant="info">已选择</Badge>}
                          </div>
                        </div>
                        <div className="grid grid-cols-2 gap-x-4 gap-y-1 text-xs text-slate-500 dark:text-slate-400">
                          <span>体积 {(scheme.metrics?.sizeMb ?? 0).toFixed(2)}MB</span>
                          <span>延迟 {(scheme.metrics?.latencyMs ?? 0).toFixed(1)}ms</span>
                          <span>精度损失 {(scheme.metrics?.accuracyLossPct ?? 0).toFixed(2)}pp</span>
                          <span>压缩率 {((scheme.stats?.compressionRatio ?? 0) * 100).toFixed(1)}%</span>
                          <span>INT8 {scheme.stats?.int8Layers ?? 0} 层</span>
                          <span>FP16 {scheme.stats?.fp16Layers ?? 0} 层</span>
                        </div>
                      </button>
                    );
                  })}
                </div>

                {selectedScheme && (
                  <>
                    <div className="grid grid-cols-3 gap-4 mb-6">
                      <div className="bg-slate-100 dark:bg-slate-800 rounded-xl p-4 text-center">
                        <p className="text-2xl font-bold text-slate-800 dark:text-white">
                          {selectedScheme.stats?.int8Layers ?? 0}
                        </p>
                        <p className="text-sm text-slate-500 dark:text-slate-400">INT8 层</p>
                      </div>
                      <div className="bg-slate-100 dark:bg-slate-800 rounded-xl p-4 text-center">
                        <p className="text-2xl font-bold text-slate-800 dark:text-white">
                          {selectedScheme.stats?.fp16Layers ?? 0}
                        </p>
                        <p className="text-sm text-slate-500 dark:text-slate-400">FP16 层</p>
                      </div>
                      <div className="bg-slate-100 dark:bg-slate-800 rounded-xl p-4 text-center">
                        <p className="text-2xl font-bold text-slate-800 dark:text-white">
                          {Math.round((selectedScheme.stats?.compressionRatio ?? 0) * 100)}%
                        </p>
                        <p className="text-sm text-slate-500 dark:text-slate-400">压缩率</p>
                      </div>
                    </div>

                    <div className="space-y-2 mb-4 max-h-64 overflow-y-auto">
                      <h3 className="text-sm font-semibold text-slate-700 dark:text-slate-300 mb-3 flex items-center gap-2">
                        <Layers className="w-4 h-4" />
                        层配置预览
                      </h3>
                      {selectedScheme.layers.map((layer) => (
                        <div
                          key={layer.name}
                          className="flex items-center justify-between bg-slate-50 dark:bg-dark-800/50 rounded-lg px-4 py-2.5"
                        >
                          <span className="text-slate-700 dark:text-slate-300 font-mono text-sm">{layer.name}</span>
                          <div className="flex items-center gap-4">
                            <span className={`px-2 py-0.5 rounded text-xs font-semibold border ${getLayerTypeColor(layer.type)}`}>
                              {layer.type}
                            </span>
                            <span className="text-slate-500 dark:text-slate-400 text-sm">
                              {formatSizeKb(layer.originalSize)} → {formatSizeKb(layer.quantizedSize)}
                            </span>
                          </div>
                        </div>
                      ))}
                    </div>
                  </>
                )}

                <p className="text-xs text-slate-400 dark:text-slate-500">
                  选定方案后点击左侧“开始量化”，后端将执行 AMCT 量化与 ATC 转换
                </p>
              </Card>
            </motion.div>
          )}

          {/* Quantization Complete */}
          {quantizationComplete && (
            <motion.div initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }}>
              <Card className="border-emerald-500/30">
                <div className="flex items-center justify-between mb-6">
                  <h2 className="text-lg font-bold text-slate-800 dark:text-white flex items-center gap-2">
                    <Sparkles className="w-5 h-5 text-emerald-500" />
                    量化完成
                  </h2>
                  <Badge variant="success">
                    <CheckCircle className="w-3 h-3 mr-1" />
                    已完成
                  </Badge>
                </div>

                <div className="grid grid-cols-3 gap-4 mb-6">
                  <div className="bg-slate-100 dark:bg-slate-800 rounded-xl p-4 text-center">
                    <p className="text-2xl font-bold text-slate-800 dark:text-white">
                      {layers.filter((item) => item.type === 'INT8').length}
                    </p>
                    <p className="text-sm text-slate-500 dark:text-slate-400">INT8 层</p>
                  </div>
                  <div className="bg-slate-100 dark:bg-slate-800 rounded-xl p-4 text-center">
                    <p className="text-2xl font-bold text-slate-800 dark:text-white">
                      {layers.filter((item) => item.type === 'FP16').length}
                    </p>
                    <p className="text-sm text-slate-500 dark:text-slate-400">FP16 层</p>
                  </div>
                  <div className="bg-slate-100 dark:bg-slate-800 rounded-xl p-4 text-center">
                    <p className="text-2xl font-bold text-emerald-600 dark:text-emerald-400">
                      {(() => {
                        const original = layers.reduce((acc, item) => acc + item.originalSize, 0);
                        const quantized = layers.reduce((acc, item) => acc + item.quantizedSize, 0);
                        return original ? `${Math.round((1 - quantized / original) * 100)}%` : '—';
                      })()}
                    </p>
                    <p className="text-sm text-slate-500 dark:text-slate-400">压缩率</p>
                  </div>
                </div>

                <div className="space-y-2 mb-6 max-h-64 overflow-y-auto">
                  <h3 className="text-sm font-semibold text-slate-700 dark:text-slate-300 mb-3 flex items-center gap-2">
                    <Layers className="w-4 h-4" />
                    层信息
                  </h3>
                  {layers.map((layer) => (
                    <div
                      key={layer.name}
                      className="flex items-center justify-between bg-slate-50 dark:bg-dark-800/50 rounded-lg px-4 py-2.5"
                    >
                      <span className="text-slate-700 dark:text-slate-300 font-mono text-sm">{layer.name}</span>
                      <div className="flex items-center gap-4">
                        <span className={`px-2 py-0.5 rounded text-xs font-semibold border ${getLayerTypeColor(layer.type)}`}>
                          {layer.type}
                        </span>
                        <span className="text-slate-500 dark:text-slate-400 text-sm">
                          {formatSizeKb(layer.originalSize)} → {formatSizeKb(layer.quantizedSize)}
                        </span>
                      </div>
                    </div>
                  ))}
                </div>

                <div className="relative">
                  <Button
                    variant="primary"
                    className="w-full"
                    icon={<Download className="w-5 h-5" />}
                    onClick={handleExport}
                  >
                    导出量化后模型（.om）
                  </Button>
                  <AnimatePresence>
                    {showExportSuccess && (
                      <motion.div
                        initial={{ opacity: 0, y: 10 }}
                        animate={{ opacity: 1, y: 0 }}
                        exit={{ opacity: 0, y: -10 }}
                        className="absolute bottom-full left-0 right-0 mb-2"
                      >
                        <div className="bg-emerald-500 text-white text-center py-2 rounded-lg text-sm">
                          ✓ 已开始下载 .om 文件
                        </div>
                      </motion.div>
                    )}
                  </AnimatePresence>
                </div>
                <p className="mt-3 text-xs text-slate-400 dark:text-slate-500">
                  模型已标记为「已量化」，可直接到「一键部署」页面推送到开发板
                </p>
              </Card>
            </motion.div>
          )}

          {/* Empty / Analyzing State */}
          {!hasPlan && !quantizationComplete && (
            <Card variant="bordered" className="border-dashed">
              <div className="text-center py-12">
                {isRunning ? (
                  <>
                    <Loader2 className="w-16 h-16 mx-auto mb-4 text-slate-400 animate-spin" />
                    <h3 className="text-lg font-semibold text-slate-700 dark:text-slate-300 mb-2">
                      {step === 'quantizing' ? '正在量化模型' : '正在分析模型'}
                    </h3>
                    <p className="text-slate-500 dark:text-slate-400 max-w-xs mx-auto">
                      {job?.message || '任务已提交，等待算法脚本上报进度'}
                    </p>
                  </>
                ) : (
                  <>
                    <Settings className="w-16 h-16 mx-auto mb-4 text-slate-300 dark:text-slate-600" />
                    <h3 className="text-lg font-semibold text-slate-700 dark:text-slate-300 mb-2">
                      配置您的量化方案
                    </h3>
                    <p className="text-slate-500 dark:text-slate-400 max-w-xs mx-auto">
                      选择模型类型和目标 NPU（{npuLabel('ascend')}），点击生成按钮获取混合精度量化配置
                    </p>
                  </>
                )}
              </div>
            </Card>
          )}
        </motion.div>
      </div>
    </div>
  );
};
