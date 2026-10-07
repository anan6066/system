/**
 * 前后端共享类型：字段名与后端响应（backend/docs/API_CONTRACT.md）逐一对齐。
 * 后端已按 camelCase 返回，无需在 api 层做映射。
 */

// --------------------------------------------------------------------------- //
// 通用
// --------------------------------------------------------------------------- //
export type NpuType = 'ascend' | 'kirin' | 'rockchip' | 'other';

export type AuthType = 'pwd' | 'key';

export interface OkResponse {
  ok: boolean;
  detail?: string | null;
}

// --------------------------------------------------------------------------- //
// 设备
// --------------------------------------------------------------------------- //
export type DeviceStatus = 'online' | 'offline' | 'busy';

export interface Device {
  id: string;
  name: string;
  ip: string;
  port: number;
  username: string;
  authType?: AuthType;
  npuType: NpuType;
  status: DeviceStatus;
  cpuUsage: number;
  memoryUsage: number;
  npuUsage?: number | null;
  note?: string | null;
  lastConnected: string;
  lastChecked?: string | null;
  lastError?: string | null;
  createdAt?: string;
  updatedAt?: string;
}

/** 新增/编辑设备时提交的字段（不再回传密码）。 */
export interface DevicePayload {
  name: string;
  ip: string;
  port: number;
  username: string;
  password?: string;
  authType?: AuthType;
  keyPath?: string;
  npuType: NpuType;
  note?: string;
}

export interface CheckResult {
  online: boolean;
  status: DeviceStatus;
  latencyMs: number | null;
  lastConnected: string | null;
  error: string | null;
}

export interface CheckAllResult {
  total: number;
  online: number;
  offline: number;
  results: Array<{
    id: string;
    name: string;
    online: boolean;
    status: DeviceStatus;
    latencyMs: number | null;
    error: string;
  }>;
}

export interface DeviceMetrics {
  cpuUsage: number;
  memoryUsage: number;
  npuUsage?: number | null;
  collectedAt: string;
}

/** 监控折线图数据点（timestamp 为 epoch 毫秒）。 */
export interface MetricSample {
  timestamp: number;
  cpu: number;
  memory: number;
}

export interface MetricsHistory {
  deviceId: string;
  samples: MetricSample[];
}

// --------------------------------------------------------------------------- //
// 模型
// --------------------------------------------------------------------------- //
export type BitWidth = 'INT8' | 'FP16' | 'FP32';

export interface QuantizationLayer {
  name: string;
  type: BitWidth;
  /** KB */
  originalSize: number;
  /** KB */
  quantizedSize: number;
}

export type ModelStatus = 'idle' | 'processing' | 'completed' | 'failed';

export interface ModelConfig {
  id: string;
  name: string;
  type: 'custom' | 'preset';
  /** 预设模型的 slug，如 'mobilenetv2' */
  preset?: string | null;
  fileSize: number;
  quantizationLayers: QuantizationLayer[];
  targetNPU: NpuType;
  createdAt: string;
  status: ModelStatus;
  baseAccuracy?: number;
  layerCount?: number;
  latestJobId?: string | null;
  updatedAt?: string;
}

export interface PresetModel {
  id: string;
  name: string;
  description: string;
  size: string;
  fileSize: number;
  baseAccuracy: number;
  layerCount: number;
  targetNPU: NpuType;
}

// --------------------------------------------------------------------------- //
// 量化任务
// --------------------------------------------------------------------------- //
export type JobStatus =
  | 'pending'
  | 'sensitivity_analysis'
  | 'scheme_search'
  | 'scheme_ready'
  | 'quantizing'
  | 'converting'
  | 'om_ready'
  | 'deploying'
  | 'deployed'
  | 'failed';

export interface QuantizationJob {
  id: string;
  modelId: string;
  modelName?: string | null;
  status: JobStatus;
  progress: number;
  message: string;
  stage: string;
  targetNPU: NpuType;
  selectedSchemeIndex: number | null;
  schemeCount: number;
  hasOm: boolean;
  omPath?: string | null;
  error?: string | null;
  createdAt: string;
  updatedAt: string;
  startedAt?: string | null;
  finishedAt?: string | null;
}

export interface SchemeStats {
  int8Layers: number;
  fp16Layers: number;
  fp32Layers: number;
  originalSizeKb: number;
  quantizedSizeKb: number;
  compressionRatio: number;
}

export interface SchemeMetrics {
  sizeMb: number;
  originalSizeMb: number;
  compressionRatio: number;
  latencyMs: number;
  accuracyLossPct: number;
}

/** 帕累托前沿里的一个位宽方案。 */
export interface QuantizationScheme {
  index: number;
  layerConfig: Record<string, BitWidth>;
  objectives: { size: number; accuracy_loss: number; latency: number };
  metrics: SchemeMetrics;
  layers: QuantizationLayer[];
  stats: SchemeStats;
  isSelected: boolean;
  recommended: boolean;
}

export type LogLevel = 'info' | 'success' | 'warning' | 'error';

export interface JobLogEntry {
  id: number;
  timestamp: string;
  stage: string;
  percent: number;
  message: string;
  level: LogLevel;
}

// --------------------------------------------------------------------------- //
// 部署
// --------------------------------------------------------------------------- //
export type DeploymentStatus = 'pending' | 'deploying' | 'success' | 'failed';

export interface DeploymentLog {
  id: string;
  timestamp: string;
  message: string;
  type: LogLevel;
}

export interface DeploymentMetrics {
  inferenceSpeed: number;
  memoryUsage: number;
  top1Accuracy: number;
}

export interface Deployment {
  id: string;
  jobId: string;
  modelId: string;
  deviceId: string;
  modelName?: string | null;
  deviceName?: string | null;
  targetDir: string;
  remoteFile?: string | null;
  status: DeploymentStatus;
  progress?: number;
  startTime: string;
  endTime?: string | null;
  logs: DeploymentLog[];
  metrics?: DeploymentMetrics | null;
  /** 'measured' = 开发板实测；'estimated' = 按方案估算 */
  metricsSource?: 'measured' | 'estimated' | null;
  error?: string | null;
  createdAt?: string;
  updatedAt?: string;
}

export interface DeploymentPayload {
  modelId: string;
  deviceId: string;
  targetDir?: string;
  runBenchmark?: boolean;
}

// --------------------------------------------------------------------------- //
// 统计与对比
// --------------------------------------------------------------------------- //
export interface PlatformStats {
  activeDevices: number;
  onlineDevices: number;
  busyDevices: number;
  totalDevices: number;
  totalModels: number;
  quantizedModels: number;
  totalJobs: number;
  runningJobs: number;
  readyJobs: number;
  failedJobs: number;
  totalDeployments: number;
  successfulDeployments: number;
  avgInferenceSpeed: number | null;
  avgLatencyMs: number | null;
  avgTop1Accuracy: number | null;
  generatedAt: string;
}

export interface ComparisonResult {
  metric: string;
  traditionalINT8: number;
  mixedPrecision: number;
  unit: string;
}

export interface RadarItem {
  metric: string;
  traditional: number;
  mixedPrecision: number;
}

export interface ComparisonResponse {
  deploymentId: string | null;
  jobId: string | null;
  modelId: string | null;
  modelName: string | null;
  mode: 'deployment' | 'job' | 'model';
  mixedPrecisionLayers: number;
  traditionalLayers: number;
  rows: ComparisonResult[];
  radar: RadarItem[];
}

// --------------------------------------------------------------------------- //
// 导航
// --------------------------------------------------------------------------- //
export type NavItem = {
  id: string;
  label: string;
  icon: string;
  path: string;
};
