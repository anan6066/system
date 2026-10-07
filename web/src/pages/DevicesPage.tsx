import React, { useCallback, useEffect, useState } from 'react';
import { motion } from 'framer-motion';
import {
  Plus,
  Pencil,
  Trash2,
  RefreshCw,
  Server,
  WifiOff,
  AlertCircle,
  Cpu,
  HardDrive,
  Activity,
  Monitor,
  ChevronRight,
  Terminal,
  CheckCircle,
  XCircle,
  Loader2,
} from 'lucide-react';
import {
  AreaChart,
  Area,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
} from 'recharts';
import { Card, Button, Input, Badge, Dialog } from '../components/ui';
import { useAppStore } from '../store/appStore';
import { useDeviceMetrics } from '../hooks/useDeviceMetrics';
import { errorMessage } from '../api';
import { deviceStatusMeta, formatDateTime, npuLabel } from '../utils/format';
import type { Device, DevicePayload, NpuType } from '../types';

interface Notice {
  type: 'success' | 'error';
  text: string;
}

const DEFAULT_FORM = {
  name: '',
  ip: '',
  port: 22,
  username: '',
  password: '',
  npuType: 'ascend' as NpuType,
};

const DeviceCard: React.FC<{
  device: Device;
  isSelected: boolean;
  onSelect: () => void;
  onEdit: () => void;
  onDelete: () => void;
  onCheck: () => void;
  onMonitor: () => void;
  isMonitoring: boolean;
  isChecking: boolean;
}> = ({ device, isSelected, onSelect, onEdit, onDelete, onCheck, onMonitor, isMonitoring, isChecking }) => {
  const statusConfig = deviceStatusMeta(device.status);

  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      whileHover={{ scale: 1.01 }}
      transition={{ duration: 0.2 }}
    >
      <div
        onClick={onSelect}
        className={`
          relative overflow-hidden rounded-2xl cursor-pointer
          bg-white dark:bg-dark-900 border transition-all duration-300
          ${isSelected
            ? 'border-slate-800 dark:border-slate-200 shadow-lg shadow-slate-200/50 dark:shadow-slate-800/50'
            : 'border-slate-200 dark:border-dark-700 hover:border-slate-300 dark:hover:border-dark-600 hover:shadow-md'
          }
        `}
      >
        <div className="absolute inset-0 opacity-[0.03] dark:opacity-[0.05]">
          <svg className="w-full h-full" xmlns="http://www.w3.org/2000/svg">
            <defs>
              <pattern id="grid" width="32" height="32" patternUnits="userSpaceOnUse">
                <path d="M0 32V0h32" fill="none" stroke="currentColor" strokeWidth="1" />
              </pattern>
            </defs>
            <rect width="100%" height="100%" fill="url(#grid)" />
          </svg>
        </div>

        <div className="relative p-5">
          <div className="flex items-start justify-between mb-4">
            <div className="flex items-center gap-3">
              <div className="w-11 h-11 rounded-xl flex items-center justify-center bg-slate-800 dark:bg-slate-700">
                <Server className="w-5 h-5 text-white" />
              </div>
              <div>
                <h3 className="font-semibold text-slate-800 dark:text-white text-base">
                  {device.name}
                </h3>
                <p className="text-sm text-slate-500 dark:text-slate-400 flex items-center gap-1">
                  <Terminal className="w-3 h-3" />
                  {device.ip}:{device.port}
                </p>
              </div>
            </div>
            <div className="flex items-center gap-2">
              <div className={`w-2 h-2 rounded-full ${statusConfig.dot} ${device.status === 'online' ? 'animate-pulse' : ''}`} />
              <Badge variant={statusConfig.badge}>{statusConfig.text}</Badge>
            </div>
          </div>

          <div className="grid grid-cols-2 gap-3 mb-4">
            <div className="bg-slate-50 dark:bg-dark-800 rounded-xl p-3">
              <p className="text-xs text-slate-500 dark:text-slate-400 mb-1">处理器</p>
              <p className="text-sm font-medium text-slate-700 dark:text-slate-300">
                {npuLabel(device.npuType)}
              </p>
            </div>
            <div className="bg-slate-50 dark:bg-dark-800 rounded-xl p-3">
              <p className="text-xs text-slate-500 dark:text-slate-400 mb-1">用户</p>
              <p className="text-sm font-medium text-slate-700 dark:text-slate-300">{device.username}</p>
            </div>
          </div>

          {device.status !== 'offline' && (
            <div className="space-y-2.5 mb-4">
              <div>
                <div className="flex justify-between text-xs mb-1.5">
                  <span className="text-slate-500 dark:text-slate-400">CPU</span>
                  <span className={`font-semibold ${device.cpuUsage > 80 ? 'text-red-500' : 'text-slate-700 dark:text-slate-300'}`}>
                    {device.cpuUsage.toFixed(1)}%
                  </span>
                </div>
                <div className="h-1.5 bg-slate-100 dark:bg-dark-800 rounded-full overflow-hidden">
                  <div
                    className={`h-full rounded-full transition-all duration-500 ${
                      device.cpuUsage > 80 ? 'bg-red-500' : 'bg-slate-800 dark:bg-slate-200'
                    }`}
                    style={{ width: `${Math.min(device.cpuUsage, 100)}%` }}
                  />
                </div>
              </div>
              <div>
                <div className="flex justify-between text-xs mb-1.5">
                  <span className="text-slate-500 dark:text-slate-400">内存</span>
                  <span className={`font-semibold ${device.memoryUsage > 80 ? 'text-red-500' : 'text-slate-700 dark:text-slate-300'}`}>
                    {device.memoryUsage.toFixed(1)}%
                  </span>
                </div>
                <div className="h-1.5 bg-slate-100 dark:bg-dark-800 rounded-full overflow-hidden">
                  <div
                    className={`h-full rounded-full transition-all duration-500 ${
                      device.memoryUsage > 80 ? 'bg-red-500' : 'bg-orange-500'
                    }`}
                    style={{ width: `${Math.min(device.memoryUsage, 100)}%` }}
                  />
                </div>
              </div>
            </div>
          )}

          {device.status === 'offline' && device.lastError && (
            <p className="mb-4 text-xs text-red-500 dark:text-red-400 line-clamp-2">
              探活失败：{device.lastError}
            </p>
          )}

          <div className="flex gap-2">
            <Button
              variant={isMonitoring ? 'primary' : 'secondary'}
              size="sm"
              className="flex-1"
              onClick={(e) => { e.stopPropagation(); onMonitor(); }}
              disabled={device.status === 'offline' && !isMonitoring}
              icon={<Activity className="w-3.5 h-3.5" />}
            >
              {isMonitoring ? '监控中' : '监控'}
            </Button>
            <Button
              variant="secondary"
              size="sm"
              onClick={(e) => { e.stopPropagation(); onCheck(); }}
              loading={isChecking}
              icon={<RefreshCw className="w-3.5 h-3.5" />}
            >
              检测
            </Button>
            <Button
              variant="secondary"
              size="sm"
              onClick={(e) => { e.stopPropagation(); onEdit(); }}
              icon={<Pencil className="w-3.5 h-3.5" />}
            />
            <Button
              variant="danger"
              size="sm"
              onClick={(e) => { e.stopPropagation(); onDelete(); }}
              icon={<Trash2 className="w-3.5 h-3.5" />}
            />
          </div>
        </div>

        {isSelected && (
          <div className="absolute right-0 top-1/2 -translate-y-1/2 translate-x-1/2">
            <ChevronRight className="w-5 h-5 text-slate-800 dark:text-white" />
          </div>
        )}
      </div>
    </motion.div>
  );
};

export const DevicesPage: React.FC = () => {
  const {
    devices,
    devicesLoading,
    devicesError,
    fetchDevices,
    addDevice,
    updateDevice,
    deleteDevice,
    checkDeviceConnection,
    checkAllDevices,
  } = useAppStore();

  const [isAddDialogOpen, setIsAddDialogOpen] = useState(false);
  const [isEditDialogOpen, setIsEditDialogOpen] = useState(false);
  const [isDeleteDialogOpen, setIsDeleteDialogOpen] = useState(false);
  const [selectedDevice, setSelectedDevice] = useState<Device | null>(null);
  const [monitoringId, setMonitoringId] = useState<string | null>(null);
  const [checkingId, setCheckingId] = useState<string | null>(null);
  const [checkingAll, setCheckingAll] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  const [notice, setNotice] = useState<Notice | null>(null);
  const [formData, setFormData] = useState(DEFAULT_FORM);

  const monitoredDevice = devices.find((item) => item.id === monitoringId) ?? null;
  const metrics = useDeviceMetrics(monitoringId, Boolean(monitoredDevice));

  useEffect(() => {
    void fetchDevices();
  }, [fetchDevices]);

  useEffect(() => {
    if (!notice) return;
    const timer = window.setTimeout(() => setNotice(null), 6000);
    return () => window.clearTimeout(timer);
  }, [notice]);

  // 选中的设备在 store 里会随探活/监控刷新，这里跟随最新数据
  const currentSelected = selectedDevice
    ? devices.find((item) => item.id === selectedDevice.id) ?? selectedDevice
    : null;

  const resetForm = useCallback(() => {
    setFormData(DEFAULT_FORM);
    setFormError(null);
  }, []);

  const handleAdd = async () => {
    if (!formData.name.trim() || !formData.ip.trim() || !formData.username.trim()) {
      setFormError('设备名称、IP、登录账号均为必填');
      return;
    }
    setSubmitting(true);
    setFormError(null);
    try {
      const payload: DevicePayload = {
        name: formData.name.trim(),
        ip: formData.ip.trim(),
        port: Number(formData.port) || 22,
        username: formData.username.trim(),
        npuType: formData.npuType,
        ...(formData.password ? { password: formData.password } : {}),
      };
      const device = await addDevice(payload);
      setIsAddDialogOpen(false);
      resetForm();
      setNotice({ type: 'success', text: `设备「${device.name}」已添加，建议点击“检测”验证连接` });
    } catch (error) {
      setFormError(errorMessage(error));
    } finally {
      setSubmitting(false);
    }
  };

  const handleEdit = async () => {
    if (!currentSelected) return;
    setSubmitting(true);
    setFormError(null);
    try {
      await updateDevice(currentSelected.id, {
        name: formData.name.trim(),
        ip: formData.ip.trim(),
        port: Number(formData.port) || 22,
        username: formData.username.trim(),
        npuType: formData.npuType,
      });
      setIsEditDialogOpen(false);
      setSelectedDevice(null);
      resetForm();
      setNotice({ type: 'success', text: '设备信息已更新' });
    } catch (error) {
      setFormError(errorMessage(error));
    } finally {
      setSubmitting(false);
    }
  };

  const handleDelete = async () => {
    if (!currentSelected) return;
    setSubmitting(true);
    try {
      await deleteDevice(currentSelected.id);
      if (monitoringId === currentSelected.id) setMonitoringId(null);
      setIsDeleteDialogOpen(false);
      setSelectedDevice(null);
      setNotice({ type: 'success', text: '设备已删除' });
    } catch (error) {
      setNotice({ type: 'error', text: errorMessage(error) });
    } finally {
      setSubmitting(false);
    }
  };

  const openEditDialog = (device: Device) => {
    setSelectedDevice(device);
    setFormError(null);
    setFormData({
      name: device.name,
      ip: device.ip,
      port: device.port,
      username: device.username,
      password: '',
      npuType: device.npuType,
    });
    setIsEditDialogOpen(true);
  };

  const openDeleteDialog = (device: Device) => {
    setSelectedDevice(device);
    setIsDeleteDialogOpen(true);
  };

  const handleCheckConnection = async (device: Device) => {
    setCheckingId(device.id);
    setNotice(null);
    try {
      const result = await checkDeviceConnection(device.id);
      setNotice(
        result.online
          ? {
              type: 'success',
              text: `${device.name}（${device.ip}）SSH 探活成功${result.latencyMs != null ? `，往返 ${result.latencyMs}ms` : ''}`,
            }
          : { type: 'error', text: `${device.name} 探活失败：${result.error ?? '未知原因'}` },
      );
      if (result.online) setSelectedDevice({ ...device, status: result.status });
    } catch (error) {
      setNotice({ type: 'error', text: errorMessage(error) });
    } finally {
      setCheckingId(null);
    }
  };

  const handleCheckAll = async () => {
    setCheckingAll(true);
    try {
      const result = await checkAllDevices();
      setNotice({
        type: result.online > 0 ? 'success' : 'error',
        text: `批量探活完成：在线 ${result.online} 台，离线 ${result.offline} 台（共 ${result.total} 台）`,
      });
    } catch (error) {
      setNotice({ type: 'error', text: errorMessage(error) });
    } finally {
      setCheckingAll(false);
    }
  };

  const toggleMonitoring = (device: Device) => {
    if (monitoringId === device.id) {
      setMonitoringId(null);
      setSelectedDevice(null);
    } else {
      setMonitoringId(device.id);
      setSelectedDevice(device);
    }
  };

  const stats = {
    total: devices.length,
    online: devices.filter((d) => d.status === 'online').length,
    offline: devices.filter((d) => d.status === 'offline').length,
    busy: devices.filter((d) => d.status === 'busy').length,
  };

  const displayDevice = monitoredDevice ? devices.find((d) => d.id === monitoredDevice.id) ?? monitoredDevice : null;
  const chartData = metrics.samples;

  return (
    <div className="max-w-7xl mx-auto">
      <motion.div
        initial={{ opacity: 0, y: -20 }}
        animate={{ opacity: 1, y: 0 }}
        className="mb-8"
      >
        <div className="flex items-center justify-between gap-4">
          <div>
            <h1 className="text-3xl md:text-4xl font-bold text-slate-800 dark:text-white mb-2">
              设备管理
            </h1>
            <p className="text-slate-500 dark:text-slate-400">
              管理 NPU 开发板的连接状态与资源监控
            </p>
          </div>
          <div className="flex items-center gap-2">
            <Button
              variant="secondary"
              onClick={handleCheckAll}
              loading={checkingAll}
              disabled={devices.length === 0}
              icon={<RefreshCw className="w-4 h-4" />}
            >
              全部检测
            </Button>
            <Button
              onClick={() => { resetForm(); setIsAddDialogOpen(true); }}
              icon={<Plus className="w-5 h-5" />}
            >
              添加设备
            </Button>
          </div>
        </div>
      </motion.div>

      {notice && (
        <motion.div
          initial={{ opacity: 0, y: -8 }}
          animate={{ opacity: 1, y: 0 }}
          className={`mb-6 flex items-start gap-2 rounded-xl border px-4 py-3 text-sm ${
            notice.type === 'success'
              ? 'border-emerald-300/60 bg-emerald-50 text-emerald-700 dark:border-emerald-500/30 dark:bg-emerald-500/10 dark:text-emerald-300'
              : 'border-red-300/60 bg-red-50 text-red-700 dark:border-red-500/30 dark:bg-red-500/10 dark:text-red-300'
          }`}
        >
          {notice.type === 'success'
            ? <CheckCircle className="w-4 h-4 mt-0.5 flex-shrink-0" />
            : <XCircle className="w-4 h-4 mt-0.5 flex-shrink-0" />}
          <span>{notice.text}</span>
        </motion.div>
      )}

      {devicesError && (
        <div className="mb-6 flex items-start gap-2 rounded-xl border border-amber-300/60 bg-amber-50 dark:border-amber-500/30 dark:bg-amber-500/10 px-4 py-3 text-sm text-amber-700 dark:text-amber-300">
          <AlertCircle className="w-4 h-4 mt-0.5 flex-shrink-0" />
          <span>设备列表加载失败：{devicesError}</span>
        </div>
      )}

      {/* Stats */}
      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.1 }}
        className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-8"
      >
        <Card className="text-center py-4">
          <p className="text-3xl font-bold text-slate-800 dark:text-white">{stats.total}</p>
          <p className="text-sm text-slate-500 dark:text-slate-400">设备总数</p>
        </Card>
        <Card className="text-center py-4 border-emerald-500/30">
          <p className="text-3xl font-bold text-emerald-600 dark:text-emerald-400">{stats.online}</p>
          <p className="text-sm text-slate-500 dark:text-slate-400">在线</p>
        </Card>
        <Card className="text-center py-4 border-slate-500/30">
          <p className="text-3xl font-bold text-slate-600 dark:text-slate-400">{stats.offline}</p>
          <p className="text-sm text-slate-500 dark:text-slate-400">离线</p>
        </Card>
        <Card className="text-center py-4 border-amber-500/30">
          <p className="text-3xl font-bold text-amber-600 dark:text-amber-400">{stats.busy}</p>
          <p className="text-sm text-slate-500 dark:text-slate-400">忙碌</p>
        </Card>
      </motion.div>

      <div className="grid grid-cols-1 xl:grid-cols-2 gap-8">
        {/* Device Grid */}
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          transition={{ delay: 0.2 }}
          className="grid grid-cols-1 md:grid-cols-2 gap-4"
        >
          {devicesLoading && devices.length === 0 && (
            <Card className="col-span-full flex items-center justify-center gap-2 py-10 text-slate-500 dark:text-slate-400">
              <Loader2 className="w-4 h-4 animate-spin" />
              正在加载设备列表...
            </Card>
          )}

          {!devicesLoading && devices.length === 0 && (
            <Card variant="bordered" className="col-span-full border-dashed py-10 text-center">
              <Server className="w-12 h-12 mx-auto mb-3 text-slate-300 dark:text-slate-600" />
              <p className="text-slate-600 dark:text-slate-300 font-medium mb-1">还没有设备</p>
              <p className="text-sm text-slate-500 dark:text-slate-400">
                点击右上角“添加设备”录入开发板的 IP 与 SSH 凭据
              </p>
            </Card>
          )}

          {devices.map((device, index) => (
            <motion.div
              key={device.id}
              initial={{ opacity: 0, y: 20 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: index * 0.05 }}
            >
              <DeviceCard
                device={device}
                isSelected={monitoringId === device.id || currentSelected?.id === device.id}
                onSelect={() => {
                  setSelectedDevice(device);
                  if (device.status !== 'offline') setMonitoringId(device.id);
                }}
                onEdit={() => openEditDialog(device)}
                onDelete={() => openDeleteDialog(device)}
                onCheck={() => void handleCheckConnection(device)}
                onMonitor={() => toggleMonitoring(device)}
                isMonitoring={monitoringId === device.id}
                isChecking={checkingId === device.id}
              />
            </motion.div>
          ))}
        </motion.div>

        {/* Monitoring Panel */}
        <motion.div
          initial={{ opacity: 0, x: 20 }}
          animate={{ opacity: 1, x: 0 }}
          transition={{ delay: 0.3 }}
        >
          {displayDevice ? (
            <Card className="sticky top-8">
              <div className="flex items-center justify-between mb-6">
                <div className="flex items-center gap-3">
                  <Monitor className="w-5 h-5 text-slate-600 dark:text-slate-400" />
                  <h2 className="text-lg font-bold text-slate-800 dark:text-white">
                    {displayDevice.name}
                  </h2>
                </div>
                <Badge variant={deviceStatusMeta(displayDevice.status).badge}>
                  {deviceStatusMeta(displayDevice.status).text}
                </Badge>
              </div>

              {displayDevice.status !== 'offline' ? (
                <div className="space-y-6">
                  {metrics.error && (
                    <div className="flex items-start gap-2 rounded-xl border border-amber-300/60 bg-amber-50 dark:border-amber-500/30 dark:bg-amber-500/10 px-3 py-2 text-xs text-amber-700 dark:text-amber-300">
                      <AlertCircle className="w-3.5 h-3.5 mt-0.5 flex-shrink-0" />
                      <span>指标采集失败：{metrics.error}（曲线保留最后一次成功数据）</span>
                    </div>
                  )}

                  <div>
                    <div className="flex items-center justify-between mb-3">
                      <div className="flex items-center gap-2">
                        <Cpu className="w-4 h-4 text-slate-600 dark:text-slate-400" />
                        <span className="text-sm font-semibold text-slate-700 dark:text-slate-300">CPU 使用率</span>
                      </div>
                      <span className="text-2xl font-bold text-slate-800 dark:text-white">
                        {displayDevice.cpuUsage.toFixed(1)}%
                      </span>
                    </div>
                    <div className="h-32">
                      <ResponsiveContainer width="100%" height="100%">
                        <AreaChart data={chartData}>
                          <defs>
                            <linearGradient id="cpuGradient" x1="0" y1="0" x2="0" y2="1">
                              <stop offset="5%" stopColor="#475569" stopOpacity={0.3} />
                              <stop offset="95%" stopColor="#475569" stopOpacity={0} />
                            </linearGradient>
                          </defs>
                          <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" className="dark:stroke-dark-700" vertical={false} />
                          <XAxis dataKey="timestamp" hide />
                          <YAxis domain={[0, 100]} hide />
                          <Tooltip
                            contentStyle={{
                              backgroundColor: 'rgba(255, 255, 255, 0.95)',
                              border: '1px solid #e5e7eb',
                              borderRadius: '8px',
                            }}
                            labelFormatter={() => ''}
                            formatter={(value) => [`${Number(value).toFixed(1)}%`, 'CPU']}
                          />
                          <Area
                            type="monotone"
                            dataKey="cpu"
                            stroke="#475569"
                            strokeWidth={2}
                            fill="url(#cpuGradient)"
                            isAnimationActive={false}
                          />
                        </AreaChart>
                      </ResponsiveContainer>
                    </div>
                  </div>

                  <div>
                    <div className="flex items-center justify-between mb-3">
                      <div className="flex items-center gap-2">
                        <HardDrive className="w-4 h-4 text-orange-500" />
                        <span className="text-sm font-semibold text-slate-700 dark:text-slate-300">内存使用率</span>
                      </div>
                      <span className="text-2xl font-bold text-slate-800 dark:text-white">
                        {displayDevice.memoryUsage.toFixed(1)}%
                      </span>
                    </div>
                    <div className="h-32">
                      <ResponsiveContainer width="100%" height="100%">
                        <AreaChart data={chartData}>
                          <defs>
                            <linearGradient id="memoryGradient" x1="0" y1="0" x2="0" y2="1">
                              <stop offset="5%" stopColor="#f97316" stopOpacity={0.3} />
                              <stop offset="95%" stopColor="#f97316" stopOpacity={0} />
                            </linearGradient>
                          </defs>
                          <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" className="dark:stroke-dark-700" vertical={false} />
                          <XAxis dataKey="timestamp" hide />
                          <YAxis domain={[0, 100]} hide />
                          <Tooltip
                            contentStyle={{
                              backgroundColor: 'rgba(255, 255, 255, 0.95)',
                              border: '1px solid #e5e7eb',
                              borderRadius: '8px',
                            }}
                            labelFormatter={() => ''}
                            formatter={(value) => [`${Number(value).toFixed(1)}%`, '内存']}
                          />
                          <Area
                            type="monotone"
                            dataKey="memory"
                            stroke="#f97316"
                            strokeWidth={2}
                            fill="url(#memoryGradient)"
                            isAnimationActive={false}
                          />
                        </AreaChart>
                      </ResponsiveContainer>
                    </div>
                  </div>

                  <div className="pt-4 border-t border-slate-200 dark:border-dark-700">
                    <div className="grid grid-cols-2 gap-4 text-sm">
                      <div>
                        <span className="text-slate-500">NPU 类型</span>
                        <p className="font-semibold text-slate-800 dark:text-white">
                          {npuLabel(displayDevice.npuType)}
                        </p>
                      </div>
                      <div>
                        <span className="text-slate-500">最后连接</span>
                        <p className="font-semibold text-slate-800 dark:text-white">
                          {formatDateTime(displayDevice.lastConnected)}
                        </p>
                      </div>
                      <div>
                        <span className="text-slate-500">NPU 占用</span>
                        <p className="font-semibold text-slate-800 dark:text-white">
                          {displayDevice.npuUsage != null ? `${displayDevice.npuUsage}%` : '—'}
                        </p>
                      </div>
                      <div>
                        <span className="text-slate-500">采样点</span>
                        <p className="font-semibold text-slate-800 dark:text-white">
                          {chartData.length} / 30
                        </p>
                      </div>
                    </div>
                    <p className="mt-3 text-xs text-slate-400 dark:text-slate-500">
                      每 2 秒通过 SSH 采集一次板载指标
                    </p>
                  </div>
                </div>
              ) : (
                <div className="text-center py-12">
                  <WifiOff className="w-16 h-16 mx-auto mb-4 text-slate-300 dark:text-slate-600" />
                  <p className="text-slate-500 dark:text-slate-400">设备离线，无法监控</p>
                  <Button
                    variant="secondary"
                    size="sm"
                    className="mt-4"
                    onClick={() => void handleCheckConnection(displayDevice)}
                    loading={checkingId === displayDevice.id}
                    icon={<RefreshCw className="w-3.5 h-3.5" />}
                  >
                    重新检测
                  </Button>
                </div>
              )}
            </Card>
          ) : (
            <Card className="h-full flex items-center justify-center min-h-[400px]">
              <div className="text-center">
                <Activity className="w-16 h-16 mx-auto mb-4 text-slate-300 dark:text-slate-600" />
                <h3 className="text-lg font-semibold text-slate-700 dark:text-slate-300 mb-2">
                  选择设备进行监控
                </h3>
                <p className="text-slate-500 dark:text-slate-400">
                  点击左侧设备卡片查看实时监控数据
                </p>
              </div>
            </Card>
          )}
        </motion.div>
      </div>

      {/* Dialogs */}
      <Dialog
        open={isAddDialogOpen}
        onOpenChange={(open) => { setIsAddDialogOpen(open); if (!open) resetForm(); }}
        title="添加新设备"
        description="填写开发板的连接信息，保存后可用“检测”验证 SSH 连通性"
      >
        <div className="space-y-4">
          <Input
            label="环境名称"
            placeholder="例如：昇腾开发板-01"
            value={formData.name}
            onChange={(e) => setFormData({ ...formData, name: e.target.value })}
          />
          <Input
            label="服务器 IP"
            placeholder="192.168.1.100"
            value={formData.ip}
            onChange={(e) => setFormData({ ...formData, ip: e.target.value })}
          />
          <Input
            label="端口"
            type="number"
            placeholder="22"
            value={formData.port}
            onChange={(e) => setFormData({ ...formData, port: parseInt(e.target.value, 10) || 22 })}
          />
          <Input
            label="登录账号"
            placeholder="root"
            value={formData.username}
            onChange={(e) => setFormData({ ...formData, username: e.target.value })}
          />
          <Input
            label="登录密码"
            type="password"
            placeholder="用于 SSH 探活与推送"
            value={formData.password}
            onChange={(e) => setFormData({ ...formData, password: e.target.value })}
          />
          <div>
            <label className="block text-sm font-semibold text-slate-700 dark:text-slate-300 mb-2">NPU 类型</label>
            <div className="flex gap-3">
              <button
                type="button"
                onClick={() => setFormData({ ...formData, npuType: 'ascend' })}
                className={`
                  flex-1 py-2 px-3 rounded-lg text-sm font-semibold transition-all
                  ${formData.npuType === 'ascend'
                    ? 'bg-slate-800 dark:bg-slate-200 text-white dark:text-slate-800'
                    : 'bg-slate-100 dark:bg-dark-800 text-slate-600 dark:text-slate-300 hover:bg-slate-200 dark:hover:bg-dark-700'
                  }
                `}
              >
                昇腾 NPU
              </button>
              <button
                type="button"
                onClick={() => setFormData({ ...formData, npuType: 'rockchip' })}
                className={`
                  flex-1 py-2 px-3 rounded-lg text-sm font-semibold transition-all
                  ${formData.npuType === 'rockchip'
                    ? 'bg-orange-500 text-white'
                    : 'bg-slate-100 dark:bg-dark-800 text-slate-600 dark:text-slate-300 hover:bg-slate-200 dark:hover:bg-dark-700'
                  }
                `}
              >
                其他 NPU
              </button>
            </div>
            <p className="mt-2 text-xs text-slate-400 dark:text-slate-500">
              当前后端算法链路面向昇腾（ATC 转 .om），其他类型仅作记录
            </p>
          </div>
          {formError && <p className="text-sm text-red-500">{formError}</p>}
          <div className="flex gap-3 pt-4">
            <Button variant="secondary" className="flex-1" onClick={() => setIsAddDialogOpen(false)}>
              取消
            </Button>
            <Button className="flex-1" onClick={() => void handleAdd()} loading={submitting}>
              添加
            </Button>
          </div>
        </div>
      </Dialog>

      <Dialog
        open={isEditDialogOpen}
        onOpenChange={setIsEditDialogOpen}
        title="编辑设备"
        description="修改设备的连接信息"
      >
        <div className="space-y-4">
          <Input
            label="环境名称"
            value={formData.name}
            onChange={(e) => setFormData({ ...formData, name: e.target.value })}
          />
          <Input
            label="服务器 IP"
            value={formData.ip}
            onChange={(e) => setFormData({ ...formData, ip: e.target.value })}
          />
          <Input
            label="端口"
            type="number"
            value={formData.port}
            onChange={(e) => setFormData({ ...formData, port: parseInt(e.target.value, 10) || 22 })}
          />
          <Input
            label="登录账号"
            value={formData.username}
            onChange={(e) => setFormData({ ...formData, username: e.target.value })}
          />
          {formError && <p className="text-sm text-red-500">{formError}</p>}
          <div className="flex gap-3 pt-4">
            <Button variant="secondary" className="flex-1" onClick={() => setIsEditDialogOpen(false)}>
              取消
            </Button>
            <Button className="flex-1" onClick={() => void handleEdit()} loading={submitting}>
              保存
            </Button>
          </div>
        </div>
      </Dialog>

      <Dialog
        open={isDeleteDialogOpen}
        onOpenChange={setIsDeleteDialogOpen}
        title="删除设备"
        description={`确定要删除 "${currentSelected?.name}" 吗？此操作不可恢复。`}
      >
        <div className="flex gap-3 pt-2">
          <Button variant="secondary" className="flex-1" onClick={() => setIsDeleteDialogOpen(false)}>
            取消
          </Button>
          <Button variant="danger" className="flex-1" onClick={() => void handleDelete()} loading={submitting}>
            删除
          </Button>
        </div>
      </Dialog>
    </div>
  );
};
