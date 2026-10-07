import type {
  DeploymentStatus,
  DeviceStatus,
  JobStatus,
  ModelStatus,
  NpuType,
} from '../types';

/** NPU 展示名（对接昇腾后，kirin/rockchip 仅作兼容展示）。 */
export function npuLabel(type?: NpuType | string | null): string {
  switch (type) {
    case 'ascend':
      return '昇腾 NPU';
    case 'kirin':
      return '麒麟 NPU';
    case 'rockchip':
      return '瑞芯微 NPU';
    default:
      return '其他 NPU';
  }
}

/** 目标 NPU 下拉选项（后端默认只做昇腾，其余保留兼容）。 */
export const npuOptions = [
  { value: 'ascend', label: '昇腾 NPU', description: 'Ascend 310 / 310P 系列，ATC 转 .om' },
];

type BadgeVariant = 'default' | 'success' | 'warning' | 'error' | 'info';

export const deviceStatusMeta = (
  status: DeviceStatus,
): { text: string; dot: string; badge: BadgeVariant } => {
  switch (status) {
    case 'online':
      return { text: '在线', dot: 'bg-emerald-500', badge: 'success' };
    case 'busy':
      return { text: '忙碌', dot: 'bg-amber-500', badge: 'warning' };
    default:
      return { text: '离线', dot: 'bg-slate-400', badge: 'default' };
  }
};

export const modelStatusMeta = (
  status: ModelStatus,
): { text: string; badge: BadgeVariant } => {
  switch (status) {
    case 'processing':
      return { text: '量化中', badge: 'info' };
    case 'completed':
      return { text: '已量化', badge: 'success' };
    case 'failed':
      return { text: '失败', badge: 'error' };
    default:
      return { text: '待量化', badge: 'default' };
  }
};

/**
 * 任务状态 → 页面步骤文案。
 * step 与 QuantizationPage 的 5 步进度条一一对应：
 * config → analyzing → plan → quantizing → complete
 */
export const jobStatusMeta = (
  status: JobStatus,
): {
  text: string;
  badge: BadgeVariant;
  step: 'config' | 'analyzing' | 'plan' | 'quantizing' | 'complete';
  active: boolean;
  failed: boolean;
} => {
  switch (status) {
    case 'pending':
      return { text: '排队中', badge: 'default', step: 'analyzing', active: true, failed: false };
    case 'sensitivity_analysis':
      return { text: '敏感度分析', badge: 'info', step: 'analyzing', active: true, failed: false };
    case 'scheme_search':
      return { text: '方案搜索', badge: 'info', step: 'analyzing', active: true, failed: false };
    case 'scheme_ready':
      return { text: '待选方案', badge: 'warning', step: 'plan', active: false, failed: false };
    case 'quantizing':
      return { text: '量化中', badge: 'info', step: 'quantizing', active: true, failed: false };
    case 'converting':
      return { text: '转换 .om', badge: 'info', step: 'quantizing', active: true, failed: false };
    case 'om_ready':
      return { text: '已完成', badge: 'success', step: 'complete', active: false, failed: false };
    case 'deploying':
      return { text: '部署中', badge: 'info', step: 'complete', active: true, failed: false };
    case 'deployed':
      return { text: '已部署', badge: 'success', step: 'complete', active: false, failed: false };
    default:
      return { text: '失败', badge: 'error', step: 'config', active: false, failed: true };
  }
};

export const deploymentStatusMeta = (
  status: DeploymentStatus,
): { text: string; badge: BadgeVariant } => {
  switch (status) {
    case 'deploying':
      return { text: '部署中', badge: 'info' };
    case 'success':
      return { text: '成功', badge: 'success' };
    case 'failed':
      return { text: '失败', badge: 'error' };
    default:
      return { text: '等待中', badge: 'warning' };
  }
};

/** 12345678 → "11.8 MB"（输入单位字节）。 */
export function formatBytes(bytes?: number | null): string {
  if (!bytes || bytes <= 0) return '—';
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

/** 层体积（KB）→ 可读文本。 */
export function formatSizeKb(sizeKb?: number | null): string {
  if (!sizeKb || sizeKb <= 0) return '—';
  if (sizeKb < 1024) return `${Math.round(sizeKb)}KB`;
  return `${(sizeKb / 1024).toFixed(2)}MB`;
}

export function formatDateTime(iso?: string | null): string {
  if (!iso) return '—';
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return '—';
  return date.toLocaleString('zh-CN');
}

export function formatTime(iso?: string | null): string {
  if (!iso) return '—';
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return '—';
  return date.toLocaleTimeString('zh-CN');
}

export function percent(value?: number | null, digits = 0): string {
  if (value === null || value === undefined || Number.isNaN(value)) return '—';
  return `${value.toFixed(digits)}%`;
}
