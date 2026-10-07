import { api, buildQuery } from './client';
import type {
  CheckAllResult,
  CheckResult,
  Device,
  DeviceMetrics,
  DevicePayload,
  MetricsHistory,
  OkResponse,
} from '../types';

export const devicesApi = {
  list: () => api.get<Device[]>('/devices'),

  get: (id: string) => api.get<Device>(`/devices/${id}`),

  create: (payload: DevicePayload) => api.post<Device>('/devices', payload),

  update: (id: string, payload: Partial<DevicePayload>) =>
    api.put<Device>(`/devices/${id}`, payload),

  remove: (id: string) => api.del<OkResponse>(`/devices/${id}`),

  /** 真实 SSH 探活（"检测"按钮）。 */
  check: (id: string) => api.post<CheckResult>(`/devices/${id}/check`),

  /** 批量探活。 */
  checkAll: () => api.post<CheckAllResult>('/devices/check-all'),

  /** 板载 CPU/内存采集（监控轮询）。 */
  metrics: (id: string) => api.get<DeviceMetrics>(`/devices/${id}/metrics`),

  /** 监控折线历史点。 */
  metricsHistory: (id: string, limit = 30) =>
    api.get<MetricsHistory>(`/devices/${id}/metrics/history${buildQuery({ limit })}`),
};
