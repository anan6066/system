"""Pydantic 请求/响应模型。

字段命名与前端 src/types/index.ts 完全一致（camelCase），前端拿到的响应可直接用，
不需要在 api 层做字段映射。所有响应字段都是必填的（除显式 Optional），
避免前端出现 undefined / Invalid Date。
"""
from typing import Any, Dict, List, Optional

from pydantic import BaseModel


# --------------------------------------------------------------------------- #
# 通用
# --------------------------------------------------------------------------- #
class OkOut(BaseModel):
    ok: bool = True
    detail: Optional[str] = None


class HealthOut(BaseModel):
    status: str = "ok"
    version: str
    time: str


# --------------------------------------------------------------------------- #
# 设备
# --------------------------------------------------------------------------- #
class DeviceCreate(BaseModel):
    name: str
    ip: str
    port: int = 22
    username: str
    authType: str = "pwd"                 # 'pwd' | 'key'
    password: Optional[str] = None
    keyPath: Optional[str] = None
    npuType: str = "ascend"
    note: Optional[str] = None


class DeviceUpdate(BaseModel):
    name: Optional[str] = None
    ip: Optional[str] = None
    port: Optional[int] = None
    username: Optional[str] = None
    authType: Optional[str] = None
    password: Optional[str] = None
    keyPath: Optional[str] = None
    npuType: Optional[str] = None
    note: Optional[str] = None


class DeviceOut(BaseModel):
    """前端 Device 接口（不含密码，密码永不回传）。"""

    id: str
    name: str
    ip: str
    port: int
    username: str
    authType: str
    npuType: str
    status: str                            # 'online' | 'offline' | 'busy'
    cpuUsage: float
    memoryUsage: float
    npuUsage: Optional[float] = None
    note: Optional[str] = None
    lastConnected: Optional[str] = None
    lastChecked: Optional[str] = None
    lastError: Optional[str] = None
    createdAt: str
    updatedAt: str


class CheckOut(BaseModel):
    online: bool
    status: str
    latencyMs: Optional[float] = None
    lastConnected: Optional[str] = None
    error: Optional[str] = None


class CheckAllOut(BaseModel):
    total: int
    online: int
    offline: int
    results: List[Dict[str, Any]]


class MetricsOut(BaseModel):
    cpuUsage: float
    memoryUsage: float
    npuUsage: Optional[float] = None
    collectedAt: str


class MetricSampleOut(BaseModel):
    """设备页折线图数据点（DevicesPage 的 DeviceMetrics）。"""

    timestamp: int                          # epoch 毫秒
    cpu: float
    memory: float


class MetricsHistoryOut(BaseModel):
    deviceId: str
    samples: List[MetricSampleOut]


# --------------------------------------------------------------------------- #
# 模型
# --------------------------------------------------------------------------- #
class PresetModelOut(BaseModel):
    id: str
    name: str
    description: str
    size: str
    fileSize: int
    baseAccuracy: float
    layerCount: int
    targetNPU: str


class ModelFromPresetIn(BaseModel):
    preset: str
    name: Optional[str] = None
    targetNPU: str = "ascend"


class QuantizationLayerOut(BaseModel):
    """前端 QuantizationLayer。"""

    name: str
    type: str                               # 'INT8' | 'FP16' | 'FP32'
    originalSize: int                       # KB
    quantizedSize: int                      # KB


class ModelOut(BaseModel):
    """前端 ModelConfig。"""

    id: str
    name: str
    type: str                               # 'custom' | 'preset'
    preset: Optional[str] = None
    fileSize: int
    targetNPU: str
    status: str                             # 'idle' | 'processing' | 'completed' | 'failed'
    baseAccuracy: float
    layerCount: int
    quantizationLayers: List[QuantizationLayerOut] = []
    latestJobId: Optional[str] = None
    createdAt: str
    updatedAt: str


# --------------------------------------------------------------------------- #
# 量化任务
# --------------------------------------------------------------------------- #
class JobCreate(BaseModel):
    modelId: str
    targetNPU: Optional[str] = None


class JobOut(BaseModel):
    id: str
    modelId: str
    modelName: Optional[str] = None
    status: str
    progress: int
    message: str
    stage: str = ""
    targetNPU: str
    selectedSchemeIndex: Optional[int] = None
    schemeCount: int = 0
    hasOm: bool = False
    omPath: Optional[str] = None
    error: Optional[str] = None
    createdAt: str
    updatedAt: str
    startedAt: Optional[str] = None
    finishedAt: Optional[str] = None


class SchemeOut(BaseModel):
    index: int
    layerConfig: Dict[str, str]
    objectives: Dict[str, float]
    metrics: Dict[str, Any] = {}
    layers: List[QuantizationLayerOut] = []
    stats: Dict[str, Any] = {}
    isSelected: bool = False
    recommended: bool = False


class SelectSchemeIn(BaseModel):
    """schemeIndex 省略时由后端按膝点推荐挑一个方案。"""

    schemeIndex: Optional[int] = None
    recommended: bool = False


class JobLogOut(BaseModel):
    id: int
    timestamp: str
    stage: str
    percent: int
    message: str
    level: str


# --------------------------------------------------------------------------- #
# 部署
# --------------------------------------------------------------------------- #
class DeploymentCreate(BaseModel):
    deviceId: str
    jobId: Optional[str] = None
    modelId: Optional[str] = None           # 前端选中的是"已量化模型"，后端据此找最新 om_ready 任务
    targetDir: Optional[str] = None         # 省略时用 config.deployment.default_target_dir
    remoteDir: Optional[str] = None         # targetDir 的别名，兼容计划文档里的命名
    runBenchmark: bool = True


class DeploymentLogOut(BaseModel):
    """前端 DeploymentLog。"""

    id: str
    timestamp: str
    message: str
    type: str                               # 'info' | 'success' | 'error' | 'warning'


class DeploymentMetricsOut(BaseModel):
    """前端 Deployment.metrics。"""

    inferenceSpeed: float                   # ms
    memoryUsage: float                      # MB
    top1Accuracy: float                     # %


class DeploymentOut(BaseModel):
    """前端 Deployment（额外带上 modelName/deviceName 方便列表直接渲染）。"""

    id: str
    jobId: str
    modelId: str
    deviceId: str
    modelName: Optional[str] = None
    deviceName: Optional[str] = None
    targetDir: str
    remoteFile: Optional[str] = None
    status: str                             # 'pending' | 'deploying' | 'success' | 'failed'
    progress: int = 0
    logs: List[DeploymentLogOut] = []
    metrics: Optional[DeploymentMetricsOut] = None
    metricsSource: Optional[str] = None     # 'measured' | 'estimated'
    error: Optional[str] = None
    startTime: str
    endTime: Optional[str] = None
    createdAt: str
    updatedAt: str


# --------------------------------------------------------------------------- #
# 统计 / 对比
# --------------------------------------------------------------------------- #
class StatsOut(BaseModel):
    activeDevices: int
    onlineDevices: int
    busyDevices: int
    totalDevices: int
    totalModels: int
    quantizedModels: int
    totalJobs: int
    runningJobs: int
    readyJobs: int
    failedJobs: int
    totalDeployments: int
    successfulDeployments: int
    avgInferenceSpeed: Optional[float] = None
    avgLatencyMs: Optional[float] = None
    avgTop1Accuracy: Optional[float] = None
    generatedAt: str


class ComparisonRowOut(BaseModel):
    metric: str
    traditionalINT8: float
    mixedPrecision: float
    unit: str


class RadarItemOut(BaseModel):
    metric: str
    traditional: float
    mixedPrecision: float


class ComparisonOut(BaseModel):
    deploymentId: Optional[str] = None
    jobId: Optional[str] = None
    modelId: Optional[str] = None
    modelName: Optional[str] = None
    mode: str                               # 'deployment' | 'job' | 'model'
    mixedPrecisionLayers: int = 0
    traditionalLayers: int = 0
    rows: List[ComparisonRowOut] = []
    radar: List[RadarItemOut] = []
