// 认证状态（Zustand）：token 存 localStorage，用户信息由 /auth/me 拉取
import { create } from 'zustand'
import { tokenStore } from '@/api/client'
import { authApi } from '@/api/endpoints'
import type { User } from '@/api/types'

interface AuthState {
  user: User | null
  token: string | null
  ready: boolean
  login: (username: string, password: string) => Promise<User>
  register: (payload: {
    username: string
    password: string
    real_name?: string
    role?: 'student' | 'teacher'
    invite_code?: string
  }) => Promise<User>
  logout: () => void
  bootstrap: () => Promise<void>
}

export const useAuth = create<AuthState>((set, get) => ({
  user: null,
  token: tokenStore.get(),
  ready: false,

  login: async (username, password) => {
    const data = await authApi.login(username, password)
    tokenStore.set(data.access_token)
    set({ token: data.access_token, user: data.user, ready: true })
    return data.user
  },

  register: async (payload) => {
    const data = await authApi.register(payload)
    tokenStore.set(data.access_token)
    set({ token: data.access_token, user: data.user, ready: true })
    return data.user
  },

  logout: () => {
    tokenStore.clear()
    set({ token: null, user: null, ready: true })
  },

  bootstrap: async () => {
    const token = tokenStore.get()
    if (!token) {
      set({ ready: true, user: null, token: null })
      return
    }
    try {
      const user = await authApi.me()
      set({ user, token, ready: true })
    } catch {
      get().logout()
      set({ ready: true })
    }
  },
}))

export const isTeacher = (user: User | null) => user?.role === 'teacher' || user?.role === 'admin'
