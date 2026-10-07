/**
 * 统一 fetch 封装。
 *
 * 基址来自 VITE_API_BASE_URL（默认 '/api'，配合 vite proxy 转发到后端）。
 * 所有错误统一抛 ApiError，页面只需展示 error.message（中文，来自后端 detail）。
 */

const BASE_URL = (import.meta.env.VITE_API_BASE_URL as string | undefined) ?? '/api';

/**
 * API Key（可选）。
 *
 * 后端 config.yaml 的 server.api_key 留空时不需要；对外部署时必须与后端一致，
 * 否则所有 /api 请求都会 401。配在 .env.production / .env.development 里。
 */
const API_KEY = (import.meta.env.VITE_API_KEY as string | undefined) ?? '';

/** 给请求带上鉴权头（没配 key 时原样返回，本机开发零改动）。 */
function withApiKey(init?: RequestInit): RequestInit {
  if (!API_KEY) return init ?? {};
  const headers = new Headers(init?.headers ?? {});
  headers.set('X-API-Key', API_KEY);
  return { ...(init ?? {}), headers };
}

export class ApiError extends Error {
  status: number;

  constructor(status: number, message: string) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
  }
}

type QueryValue = string | number | boolean | undefined | null;

/** 把对象拼成 query string（跳过空值）。 */
export function buildQuery(params?: Record<string, QueryValue>): string {
  if (!params) return '';
  const search = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value === undefined || value === null || value === '') return;
    search.append(key, String(value));
  });
  const text = search.toString();
  return text ? `?${text}` : '';
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${BASE_URL}${path}`, withApiKey(init));
  } catch {
    throw new ApiError(
      0,
      '无法连接后端服务：请确认后端已启动，且 vite 代理 / VITE_API_BASE_URL 配置正确',
    );
  }

  if (!response.ok) {
    let detail = `请求失败（HTTP ${response.status}）`;
    try {
      const body = await response.json();
      if (body && typeof body.detail === 'string') detail = body.detail;
      else if (Array.isArray(body?.detail)) detail = body.detail[0]?.msg ?? detail;
    } catch {
      /* 响应不是 JSON，保留默认文案 */
    }
    throw new ApiError(response.status, detail);
  }

  if (response.status === 204) return undefined as T;
  const text = await response.text();
  if (!text) return undefined as T;
  try {
    return JSON.parse(text) as T;
  } catch {
    return text as unknown as T;
  }
}

const jsonInit = (method: string, body: unknown): RequestInit => ({
  method,
  headers: { 'Content-Type': 'application/json' },
  body: body === undefined ? undefined : JSON.stringify(body),
});

export const api = {
  get: <T>(path: string) => request<T>(path),
  post: <T>(path: string, body?: unknown) => request<T>(path, jsonInit('POST', body)),
  put: <T>(path: string, body?: unknown) => request<T>(path, jsonInit('PUT', body)),
  del: <T>(path: string) => request<T>(path, { method: 'DELETE' }),

  /** multipart 上传（ONNX 模型）。 */
  upload: <T>(path: string, file: File, extra?: Record<string, string>) => {
    const form = new FormData();
    form.append('file', file);
    Object.entries(extra ?? {}).forEach(([key, value]) => form.append(key, value));
    return request<T>(path, { method: 'POST', body: form });
  },

  /** 后端文件的直链（如 .om 下载），交给浏览器处理 Content-Disposition。 */
  fileUrl: (path: string) => `${BASE_URL}${path}`,
};

/** 从 Content-Disposition 里取文件名（优先 RFC 5987 的 filename*）。 */
function filenameFromDisposition(value: string): string {
  const star = /filename\*=UTF-8''([^;]+)/i.exec(value);
  if (star?.[1]) {
    try {
      return decodeURIComponent(star[1]);
    } catch {
      /* 编码异常就退回下面的普通形式 */
    }
  }
  const plain = /filename="?([^";]+)"?/i.exec(value);
  return plain?.[1] ?? '';
}

/**
 * 触发浏览器下载。
 *
 * 走 fetch 而不是 <a href> 直链：鉴权头没法加在直链上，开了 API Key 之后
 * 直链会拿到 401。这里先取回 blob 再落盘，顺便沿用后端给的文件名。
 */
export async function downloadFile(path: string, fallbackName = 'download') {
  const response = await fetch(`${BASE_URL}${path}`, withApiKey());
  if (!response.ok) {
    let detail = `下载失败（HTTP ${response.status}）`;
    try {
      const body = await response.json();
      if (body && typeof body.detail === 'string') detail = body.detail;
    } catch {
      /* 响应不是 JSON，保留默认文案 */
    }
    throw new ApiError(response.status, detail);
  }

  const blob = await response.blob();
  const name = filenameFromDisposition(
    response.headers.get('content-disposition') ?? '',
  ) || fallbackName;
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = name;
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
  URL.revokeObjectURL(url);
}

/** 把任意异常转成可展示文案。 */
export function errorMessage(error: unknown): string {
  if (error instanceof ApiError) return error.message;
  if (error instanceof Error) return error.message;
  return '未知错误';
}
