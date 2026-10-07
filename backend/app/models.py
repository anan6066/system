"""SQLModel 表模型。

约定（与前端 src/types/index.ts 对齐）：
* 列名一律 camelCase，前端拿到的响应字段无需再做映射；
* 主键为 32 位 hex 字符串（uuid4().hex），Scheme/JobLog 用自增整型；
* 时间戳统一 `datetime.utcnow().isoformat() + 'Z'`，前端 new Date(...) 会正确按本地时区展示。
"""
from datetime import datetime
from typing import Optional
from uuid import uuid4

from sqlmodel import Field, SQLModel


def now_iso() -> str:
    """UTC ISO8601（带 Z 后缀），供前端 new Date() 解析。"""
    return datetime.utcnow().replace(microsecond=0).isoformat() + "Z"


def new_id() -> str:
    return uuid4().hex


# --------------------------------------------------------------------------- #
# 设备
# --------------------------------------------------------------------------- #
class Device(SQLModel, table=True):
    __tablename__ = "device"

    id: str = Field(default_factory=new_id, primary_key=True)
    name: str
    ip: str
    port: int = 22
    username: str
    authType: str = "pwd"                 # 'pwd' | 'key'
    password: Optional[str] = None
    keyPath: Optional[str] = None
    npuType: str = "ascend"               # 昇腾为主，兼容 kirin/rockchip/other 展示
    status: str = "offline"               # 'online' | 'offline' | 'busy'
    cpuUsage: float = 0.0                 # 最近一次采集值，前端卡片直接展示
    memoryUsage: float = 0.0
    npuUsage: Optional[float] = None
    note: Optional[str] = None
    lastConnected: Optional[str] = None   # 最近一次探活成功时间
    lastChecked: Optional[str] = None     # 最近一次探活（无论成败）
    lastError: Optional[str] = None       # 最近一次探活失败原因
    createdAt: str = Field(default_factory=now_iso)
    updatedAt: str = Field(default_factory=now_iso)


# --------------------------------------------------------------------------- #
# 模型（ONNX）
# --------------------------------------------------------------------------- #
class Model(SQLModel, table=True):
    __tablename__ = "model"

    id: str = Field(default_factory=new_id, primary_key=True)
    name: str
    type: str = "custom"                  # 'custom' | 'preset'
    preset: Optional[str] = None          # 'mobilenetv2' / 'resnet18' / ...
    filePath: str = ""
    fileSize: int = 0
    targetNPU: str = "ascend"
    status: str = "idle"                  # 'idle' | 'processing' | 'completed' | 'failed'
    baseAccuracy: float = 72.0            # 浮点基线 Top-1（用于估算量化后精度）
    layerCount: int = 0
    createdAt: str = Field(default_factory=now_iso)
    updatedAt: str = Field(default_factory=now_iso)


# --------------------------------------------------------------------------- #
# 量化任务（8 态状态机）
# --------------------------------------------------------------------------- #
class QuantizationJob(SQLModel, table=True):
    __tablename__ = "quantizationjob"

    id: str = Field(default_factory=new_id, primary_key=True)
    modelId: str = Field(foreign_key="model.id", index=True)
    # pending | sensitivity_analysis | scheme_search | scheme_ready
    # | quantizing | converting | om_ready | deploying | deployed | failed | canceled
    status: str = "pending"
    progress: int = 0
    message: str = ""
    stage: str = ""                       # 最近一次脚本上报的 stage
    targetNPU: str = "ascend"
    selectedSchemeIndex: Optional[int] = None
    schemeCount: int = 0
    sensitivityFile: Optional[str] = None
    schemesFile: Optional[str] = None
    quantizedFile: Optional[str] = None
    omPath: Optional[str] = None
    error: Optional[str] = None
    startedAt: Optional[str] = None
    finishedAt: Optional[str] = None
    createdAt: str = Field(default_factory=now_iso)
    updatedAt: str = Field(default_factory=now_iso)


class Scheme(SQLModel, table=True):
    """帕累托前沿里的一个位宽方案。"""

    __tablename__ = "scheme"

    id: Optional[int] = Field(default=None, primary_key=True)
    jobId: str = Field(foreign_key="quantizationjob.id", index=True)
    index: int
    layerConfig: str = "{}"               # JSON: {层名: 'INT8'|'FP16'|'FP32'}
    objectives: str = "{}"                # JSON: {size, accuracy_loss, latency}
    metrics: str = "{}"                   # JSON: {sizeMb, latencyMs, accuracyLossPct, ...}
    layersJson: str = "[]"                # JSON: [{name, type, originalSize, quantizedSize}]
    sizeKb: float = 0.0
    quantizedSizeKb: float = 0.0
    compressionRatio: float = 0.0         # 0~1，越大压缩越少
    int8Layers: int = 0
    fp16Layers: int = 0
    fp32Layers: int = 0
    isSelected: bool = False
    createdAt: str = Field(default_factory=now_iso)


class JobLog(SQLModel, table=True):
    """任务进度日志：轮询进度时前端可一并展示。"""

    __tablename__ = "joblog"

    id: Optional[int] = Field(default=None, primary_key=True)
    jobId: str = Field(foreign_key="quantizationjob.id", index=True)
    timestamp: str = Field(default_factory=now_iso)
    stage: str = ""
    percent: int = 0
    message: str = ""
    level: str = "info"                   # 'info' | 'success' | 'warning' | 'error'


# --------------------------------------------------------------------------- #
# 部署推送
# --------------------------------------------------------------------------- #
class Deployment(SQLModel, table=True):
    __tablename__ = "deployment"

    id: str = Field(default_factory=new_id, primary_key=True)
    jobId: str = Field(foreign_key="quantizationjob.id", index=True)
    modelId: str = Field(foreign_key="model.id", index=True)
    deviceId: str = Field(foreign_key="device.id", index=True)
    targetDir: str = "/data/models"
    remoteFile: Optional[str] = None
    status: str = "pending"               # 'pending' | 'deploying' | 'success' | 'failed'
    progress: int = 0
    logs: str = "[]"                      # JSON: [{id, timestamp, message, type}]
    metrics: Optional[str] = None         # JSON: {inferenceSpeed, memoryUsage, top1Accuracy}
    metricsSource: Optional[str] = None   # 'measured' | 'estimated'
    error: Optional[str] = None
    startTime: str = Field(default_factory=now_iso)
    endTime: Optional[str] = None
    createdAt: str = Field(default_factory=now_iso)
    updatedAt: str = Field(default_factory=now_iso)
