// 异步任务轮询：解析/出题/阅卷共用（后端 1.5s 轮询设计）
import { useQuery } from '@tanstack/react-query'
import { jobApi } from '@/api/endpoints'

export function useJobPolling(taskId?: string | null, interval = 1500) {
  return useQuery({
    queryKey: ['job', taskId],
    queryFn: () => jobApi.get(taskId as string),
    enabled: Boolean(taskId),
    refetchInterval: (query) => {
      const status = query.state.data?.status
      return status === 'succeeded' || status === 'failed' ? false : interval
    },
    refetchOnWindowFocus: false,
  })
}
