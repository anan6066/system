import { api, buildQuery } from './client';
import type { ComparisonResponse, PlatformStats } from '../types';

export const statsApi = {
  /** 首页统计（真实聚合）。 */
  get: () => api.get<PlatformStats>('/stats'),
};

export const comparisonApi = {
  /** 传统全 INT8 基线 vs 实际混合精度方案；三者传其一即可。 */
  get: (params: { deploymentId?: string; jobId?: string; modelId?: string }) =>
    api.get<ComparisonResponse>(`/comparison${buildQuery(params)}`),
};

export const metaApi = {
  /** 枚举与约定速查（排查联调问题时很有用）。 */
  get: () => api.get<Record<string, unknown>>('/meta'),
};
