// 统一 HTTP 客户端：解包后端 {code,message,data} 信封 + 401 自动登出 + 错误提示文本
import axios, { AxiosError, type AxiosRequestConfig } from 'axios'
import type { Envelope } from './types'

export const API_BASE = import.meta.env.VITE_API_BASE ?? '/api/v1'
const TOKEN_KEY = 'course-agent-token'

export class ApiError extends Error {
  code: number
  status: number

  constructor(message: string, code: number, status: number) {
    super(message)
    this.name = 'ApiError'
    this.code = code
    this.status = status
  }
}

export const tokenStore = {
  get: () => localStorage.getItem(TOKEN_KEY),
  set: (token: string) => localStorage.setItem(TOKEN_KEY, token),
  clear: () => localStorage.removeItem(TOKEN_KEY),
}

const http = axios.create({ baseURL: API_BASE, timeout: 120_000 })

http.interceptors.request.use((config) => {
  const token = tokenStore.get()
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

let onUnauthorized: (() => void) | null = null

/** 由 App 注入（跳转登录页），避免 store 与 axios 循环依赖 */
export const setUnauthorizedHandler = (handler: () => void) => {
  onUnauthorized = handler
}

http.interceptors.response.use(
  (resp) => resp,
  (error: AxiosError<Envelope<unknown>>) => {
    const status = error.response?.status ?? 0
    const body = error.response?.data
    if (status === 401) {
      tokenStore.clear()
      onUnauthorized?.()
    }
    const message =
      body?.message ||
      (status === 0 ? '网络异常，请检查后端服务是否启动' : error.message) ||
      '请求失败'
    return Promise.reject(new ApiError(message, body?.code ?? status, status))
  },
)

async function request<T>(config: AxiosRequestConfig): Promise<T> {
  const resp = await http.request<Envelope<T>>(config)
  const body = resp.data
  if (body && typeof body === 'object' && 'code' in body && body.code !== 0) {
    throw new ApiError(body.message || '请求失败', body.code, resp.status)
  }
  return body?.data as T
}

export const api = {
  get: <T>(url: string, params?: Record<string, unknown>) =>
    request<T>({ url, method: 'GET', params }),
  post: <T>(url: string, data?: unknown, params?: Record<string, unknown>) =>
    request<T>({ url, method: 'POST', data, params }),
  put: <T>(url: string, data?: unknown) => request<T>({ url, method: 'PUT', data }),
  patch: <T>(url: string, data?: unknown) => request<T>({ url, method: 'PATCH', data }),
  delete: <T>(url: string) => request<T>({ url, method: 'DELETE' }),
  upload: <T>(url: string, file: File, field = 'file') => {
    const form = new FormData()
    form.append(field, file)
    return request<T>({
      url,
      method: 'POST',
      data: form,
      headers: { 'Content-Type': 'multipart/form-data' },
      timeout: 300_000,
    })
  },
}

export function errorText(error: unknown): string {
  if (error instanceof ApiError) return error.message
  if (error instanceof Error) return error.message
  return '未知错误'
}
