import { useCallback, useEffect, useRef, useState } from 'react';
import { devicesApi, errorMessage } from '../api';
import { useAppStore } from '../store/appStore';
import type { MetricSample } from '../types';

const POLL_INTERVAL_MS = 2000;
const MAX_POINTS = 30;

export interface DeviceMetricsState {
  /** 折线图数据点（最多 30 个，2s 一个点，与后端历史缓冲一致） */
  samples: MetricSample[];
  latest: { cpu: number; memory: number } | null;
  error: string | null;
  loading: boolean;
}

/**
 * 设备监控：负责 2s 轮询 `GET /api/devices/{id}/metrics`，
 * 首次进入时用 `GET /api/devices/{id}/metrics/history` 填充历史曲线，
 * 并把最新占用值同步回 store（设备卡片上的 CPU/内存百分比）。
 *
 * 采集失败（后端 502，例如板子连不上）只记录 error，不清空已有曲线。
 */
export function useDeviceMetrics(deviceId: string | null, enabled: boolean): DeviceMetricsState {
  const applyDevicePatch = useAppStore((state) => state.applyDevicePatch);
  const [samples, setSamples] = useState<MetricSample[]>([]);
  const [latest, setLatest] = useState<{ cpu: number; memory: number } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const timerRef = useRef<number | null>(null);

  const stop = useCallback(() => {
    if (timerRef.current !== null) {
      window.clearInterval(timerRef.current);
      timerRef.current = null;
    }
  }, []);

  useEffect(() => {
    if (!deviceId || !enabled) {
      stop();
      setSamples([]);
      setLatest(null);
      setError(null);
      return;
    }

    let cancelled = false;

    const tick = async () => {
      try {
        const metrics = await devicesApi.metrics(deviceId);
        if (cancelled) return;
        setError(null);
        setLatest({ cpu: metrics.cpuUsage, memory: metrics.memoryUsage });
        setSamples((prev) =>
          [
            ...prev,
            { timestamp: Date.now(), cpu: metrics.cpuUsage, memory: metrics.memoryUsage },
          ].slice(-MAX_POINTS),
        );
        applyDevicePatch(deviceId, {
          cpuUsage: metrics.cpuUsage,
          memoryUsage: metrics.memoryUsage,
          npuUsage: metrics.npuUsage ?? null,
          status: 'online',
        });
      } catch (err) {
        if (cancelled) return;
        setError(errorMessage(err));
      }
    };

    const start = async () => {
      setLoading(true);
      try {
        const history = await devicesApi.metricsHistory(deviceId, MAX_POINTS);
        if (cancelled) return;
        setSamples(history.samples);
        if (history.samples.length > 0) {
          const last = history.samples[history.samples.length - 1];
          setLatest({ cpu: last.cpu, memory: last.memory });
        }
      } catch {
        /* 历史点拿不到不影响实时轮询 */
      } finally {
        if (!cancelled) setLoading(false);
      }
      if (cancelled) return;
      void tick();
      timerRef.current = window.setInterval(tick, POLL_INTERVAL_MS);
    };

    void start();

    return () => {
      cancelled = true;
      stop();
    };
  }, [deviceId, enabled, applyDevicePatch, stop]);

  return { samples, latest, error, loading };
}
