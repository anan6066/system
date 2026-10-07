import { api, buildQuery, downloadFile } from './client';
import type {
  JobLogEntry,
  JobStatus,
  NpuType,
  OkResponse,
  QuantizationJob,
  QuantizationLayer,
  QuantizationScheme,
} from '../types';

const BASE_PATH = '/quantization/jobs';

export const jobsApi = {
  /** 创建量化任务（① HAWQ + ② NSGA-II 异步执行）。 */
  create: (modelId: string, targetNPU?: NpuType) =>
    api.post<QuantizationJob>(BASE_PATH, {
      modelId,
      ...(targetNPU ? { targetNPU } : {}),
    }),

  list: (params?: { modelId?: string; status?: JobStatus; limit?: number }) =>
    api.get<QuantizationJob[]>(`${BASE_PATH}${buildQuery(params)}`),

  /** 进度轮询（建议 1~2s 一次）。 */
  get: (id: string) => api.get<QuantizationJob>(`${BASE_PATH}/${id}`),

  /** 帕累托前沿（每个方案含 layerConfig / metrics / layers / stats）。 */
  schemes: (id: string) => api.get<QuantizationScheme[]>(`${BASE_PATH}/${id}/schemes`),

  /** 选定方案的层明细。 */
  layers: (id: string) => api.get<QuantizationLayer[]>(`${BASE_PATH}/${id}/layers`),

  /** 各层敏感度 {层名: 敏感度}。 */
  sensitivity: (id: string) => api.get<Record<string, number>>(`${BASE_PATH}/${id}/sensitivity`),

  logs: (id: string) => api.get<JobLogEntry[]>(`${BASE_PATH}/${id}/logs`),

  /** 选方案并启动 ④ AMCT + ⑤ ATC；不传 index 时后端按膝点推荐。 */
  select: (id: string, schemeIndex?: number) =>
    api.post<QuantizationJob>(
      `${BASE_PATH}/${id}/select`,
      schemeIndex === undefined ? {} : { schemeIndex },
    ),

  cancel: (id: string) => api.post<QuantizationJob>(`${BASE_PATH}/${id}/cancel`),

  remove: (id: string) => api.del<OkResponse>(`${BASE_PATH}/${id}`),

  /** 导出/下载 .om（浏览器直链下载）。 */
  downloadOm: (id: string, fallbackName = 'model.om') =>
    downloadFile(`${BASE_PATH}/${id}/om/download`, fallbackName),
};
