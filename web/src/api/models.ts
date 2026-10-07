import { api } from './client';
import type { ModelConfig, NpuType, OkResponse, PresetModel, QuantizationLayer } from '../types';

export const modelsApi = {
  list: () => api.get<ModelConfig[]>('/models'),

  get: (id: string) => api.get<ModelConfig>(`/models/${id}`),

  /** 上传自定义 ONNX（multipart，字段名 file）。 */
  upload: (file: File, options?: { targetNPU?: NpuType; baseAccuracy?: number }) =>
    api.upload<ModelConfig>('/models', file, {
      ...(options?.targetNPU ? { targetNPU: options.targetNPU } : {}),
      ...(options?.baseAccuracy !== undefined
        ? { baseAccuracy: String(options.baseAccuracy) }
        : {}),
    }),

  /** 预设模型列表（下拉数据源）。 */
  presets: () => api.get<PresetModel[]>('/models/presets'),

  /** 把预设模型实例化成一条模型记录（之后即可走量化流程）。 */
  createFromPreset: (preset: string, options?: { name?: string; targetNPU?: NpuType }) =>
    api.post<ModelConfig>('/models/preset', {
      preset,
      ...(options?.name ? { name: options.name } : {}),
      ...(options?.targetNPU ? { targetNPU: options.targetNPU } : {}),
    }),

  /** 模型层信息（未量化时是全 FP32 结构，量化后是选定方案的真实位宽）。 */
  layers: (id: string) => api.get<QuantizationLayer[]>(`/models/${id}/layers`),

  downloadUrl: (id: string) => api.fileUrl(`/models/${id}/download`),

  remove: (id: string) => api.del<OkResponse>(`/models/${id}`),
};
