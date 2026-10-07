import { api, buildQuery } from './client';
import type {
  Deployment,
  DeploymentPayload,
  DeploymentStatus,
  OkResponse,
} from '../types';

export const deploymentsApi = {
  list: (params?: {
    modelId?: string;
    deviceId?: string;
    jobId?: string;
    status?: DeploymentStatus;
    limit?: number;
  }) => api.get<Deployment[]>(`/deployments${buildQuery(params)}`),

  /** 一键部署：后端异步 SFTP 推送并回填性能指标。 */
  create: (payload: DeploymentPayload) => api.post<Deployment>('/deployments', payload),

  /** 部署详情 / 日志轮询。 */
  get: (id: string) => api.get<Deployment>(`/deployments/${id}`),

  retry: (id: string) => api.post<Deployment>(`/deployments/${id}/retry`),

  remove: (id: string) => api.del<OkResponse>(`/deployments/${id}`),
};
