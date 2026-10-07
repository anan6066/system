import { create } from 'zustand';
import {
  comparisonApi,
  deploymentsApi,
  devicesApi,
  errorMessage,
  modelsApi,
  statsApi,
} from '../api';
import type {
  CheckAllResult,
  CheckResult,
  ComparisonResponse,
  Deployment,
  DeploymentPayload,
  Device,
  DevicePayload,
  ModelConfig,
  NpuType,
  PlatformStats,
  PresetModel,
} from '../types';

type Theme = 'light' | 'dark';

interface AppState {
  // Theme
  theme: Theme;
  setTheme: (theme: Theme) => void;
  toggleTheme: () => void;

  // Navigation
  currentPage: string;
  setCurrentPage: (page: string) => void;

  // ---------------- Devices（真实接口） ----------------
  devices: Device[];
  devicesLoading: boolean;
  devicesError: string | null;
  fetchDevices: () => Promise<void>;
  addDevice: (payload: DevicePayload) => Promise<Device>;
  updateDevice: (id: string, payload: Partial<DevicePayload>) => Promise<Device>;
  deleteDevice: (id: string) => Promise<void>;
  checkDeviceConnection: (id: string) => Promise<CheckResult>;
  checkAllDevices: () => Promise<CheckAllResult>;
  /** 监控轮询就地更新 CPU/内存，不触发一次完整请求 */
  applyDevicePatch: (id: string, patch: Partial<Device>) => void;

  // ---------------- Models ----------------
  models: ModelConfig[];
  modelsLoading: boolean;
  modelsError: string | null;
  fetchModels: () => Promise<void>;
  uploadModel: (
    file: File,
    options?: { targetNPU?: NpuType; baseAccuracy?: number },
  ) => Promise<ModelConfig>;
  createModelFromPreset: (
    presetId: string,
    options?: { name?: string; targetNPU?: NpuType },
  ) => Promise<ModelConfig>;
  deleteModel: (id: string) => Promise<void>;

  presets: PresetModel[];
  presetsError: string | null;
  fetchPresets: () => Promise<void>;

  // ---------------- Deployments ----------------
  deployments: Deployment[];
  deploymentsLoading: boolean;
  deploymentsError: string | null;
  fetchDeployments: () => Promise<void>;
  createDeployment: (payload: DeploymentPayload) => Promise<Deployment>;
  refreshDeployment: (id: string) => Promise<Deployment>;
  retryDeployment: (id: string) => Promise<Deployment>;
  deleteDeployment: (id: string) => Promise<void>;

  // ---------------- Stats / Comparison ----------------
  stats: PlatformStats | null;
  statsLoading: boolean;
  statsError: string | null;
  fetchStats: () => Promise<void>;

  comparison: ComparisonResponse | null;
  comparisonLoading: boolean;
  comparisonError: string | null;
  fetchComparison: (params: {
    deploymentId?: string;
    jobId?: string;
    modelId?: string;
  }) => Promise<void>;
  clearComparison: () => void;

  // UI State
  sidebarCollapsed: boolean;
  toggleSidebar: () => void;
}

export const useAppStore = create<AppState>((set, get) => ({
  // ---------------- Theme ----------------
  theme: 'light',
  setTheme: (theme) => {
    set({ theme });
    if (typeof document !== 'undefined') {
      document.documentElement.classList.remove('light', 'dark');
      document.documentElement.classList.add(theme);
    }
  },
  toggleTheme: () => {
    get().setTheme(get().theme === 'dark' ? 'light' : 'dark');
  },

  // ---------------- Navigation ----------------
  currentPage: 'home',
  setCurrentPage: (page) => set({ currentPage: page }),

  // ---------------- Devices ----------------
  devices: [],
  devicesLoading: false,
  devicesError: null,
  fetchDevices: async () => {
    set({ devicesLoading: true });
    try {
      const devices = await devicesApi.list();
      set({ devices, devicesError: null });
    } catch (error) {
      set({ devicesError: errorMessage(error) });
    } finally {
      set({ devicesLoading: false });
    }
  },
  addDevice: async (payload) => {
    const device = await devicesApi.create(payload);
    set((state) => ({ devices: [...state.devices, device], devicesError: null }));
    return device;
  },
  updateDevice: async (id, payload) => {
    const device = await devicesApi.update(id, payload);
    set((state) => ({
      devices: state.devices.map((item) => (item.id === id ? device : item)),
    }));
    return device;
  },
  deleteDevice: async (id) => {
    await devicesApi.remove(id);
    set((state) => ({ devices: state.devices.filter((item) => item.id !== id) }));
  },
  checkDeviceConnection: async (id) => {
    const result = await devicesApi.check(id);
    set((state) => ({
      devices: state.devices.map((item) =>
        item.id === id
          ? {
              ...item,
              status: result.status,
              lastConnected: result.lastConnected ?? item.lastConnected,
              lastError: result.error,
              lastChecked: new Date().toISOString(),
            }
          : item,
      ),
    }));
    return result;
  },
  checkAllDevices: async () => {
    const result = await devicesApi.checkAll();
    await get().fetchDevices();
    return result;
  },
  applyDevicePatch: (id, patch) =>
    set((state) => ({
      devices: state.devices.map((item) => (item.id === id ? { ...item, ...patch } : item)),
    })),

  // ---------------- Models ----------------
  models: [],
  modelsLoading: false,
  modelsError: null,
  fetchModels: async () => {
    set({ modelsLoading: true });
    try {
      const models = await modelsApi.list();
      set({ models, modelsError: null });
    } catch (error) {
      set({ modelsError: errorMessage(error) });
    } finally {
      set({ modelsLoading: false });
    }
  },
  uploadModel: async (file, options) => {
    const model = await modelsApi.upload(file, options);
    set((state) => ({ models: [model, ...state.models], modelsError: null }));
    return model;
  },
  createModelFromPreset: async (presetId, options) => {
    const model = await modelsApi.createFromPreset(presetId, options);
    set((state) => ({ models: [model, ...state.models], modelsError: null }));
    return model;
  },
  deleteModel: async (id) => {
    await modelsApi.remove(id);
    set((state) => ({
      models: state.models.filter((item) => item.id !== id),
      // 该模型的部署记录后端已级联删除，本地一并移除
      deployments: state.deployments.filter((item) => item.modelId !== id),
    }));
  },

  presets: [],
  presetsError: null,
  fetchPresets: async () => {
    try {
      const presets = await modelsApi.presets();
      set({ presets, presetsError: null });
    } catch (error) {
      set({ presetsError: errorMessage(error) });
    }
  },

  // ---------------- Deployments ----------------
  deployments: [],
  deploymentsLoading: false,
  deploymentsError: null,
  fetchDeployments: async () => {
    set({ deploymentsLoading: true });
    try {
      const deployments = await deploymentsApi.list({ limit: 50 });
      set({ deployments, deploymentsError: null });
    } catch (error) {
      set({ deploymentsError: errorMessage(error) });
    } finally {
      set({ deploymentsLoading: false });
    }
  },
  createDeployment: async (payload) => {
    const deployment = await deploymentsApi.create(payload);
    set((state) => ({ deployments: [deployment, ...state.deployments] }));
    return deployment;
  },
  refreshDeployment: async (id) => {
    const deployment = await deploymentsApi.get(id);
    set((state) => ({
      deployments: state.deployments.map((item) => (item.id === id ? deployment : item)),
    }));
    return deployment;
  },
  retryDeployment: async (id) => {
    const deployment = await deploymentsApi.retry(id);
    set((state) => ({
      deployments: state.deployments.map((item) => (item.id === id ? deployment : item)),
    }));
    return deployment;
  },
  deleteDeployment: async (id) => {
    await deploymentsApi.remove(id);
    set((state) => ({
      deployments: state.deployments.filter((item) => item.id !== id),
    }));
  },

  // ---------------- Stats ----------------
  stats: null,
  statsLoading: false,
  statsError: null,
  fetchStats: async () => {
    set({ statsLoading: true });
    try {
      const stats = await statsApi.get();
      set({ stats, statsError: null });
    } catch (error) {
      set({ statsError: errorMessage(error) });
    } finally {
      set({ statsLoading: false });
    }
  },

  // ---------------- Comparison ----------------
  comparison: null,
  comparisonLoading: false,
  comparisonError: null,
  fetchComparison: async (params) => {
    set({ comparisonLoading: true });
    try {
      const comparison = await comparisonApi.get(params);
      set({ comparison, comparisonError: null });
    } catch (error) {
      set({ comparison: null, comparisonError: errorMessage(error) });
    } finally {
      set({ comparisonLoading: false });
    }
  },
  clearComparison: () => set({ comparison: null, comparisonError: null }),

  // ---------------- UI ----------------
  sidebarCollapsed: false,
  toggleSidebar: () =>
    set((state) => ({ sidebarCollapsed: !state.sidebarCollapsed })),
}));
