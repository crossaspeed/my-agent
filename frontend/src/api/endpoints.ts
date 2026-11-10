// 后端接口封装：与 app/api/v1 一一对应，页面只依赖此文件
import { api } from './client'
import type {
  Attempt,
  AttemptReport,
  ChunkPage,
  Course,
  Doc,
  ErrorHeatCell,
  GradingStatus,
  Job,
  KPMastery,
  KnowledgePoint,
  Member,
  Overview,
  Paper,
  PaperListItem,
  PaperStats,
  Question,
  QuestionPage,
  RetrievedChunk,
  TokenPayload,
  TutorOpening,
  TutorSession,
  TutorSessionDetail,
  User,
} from './types'

export const authApi = {
  login: (username: string, password: string) =>
    api.post<TokenPayload>('/auth/login', { username, password }),
  register: (payload: {
    username: string
    password: string
    real_name?: string
    role?: 'student' | 'teacher'
    invite_code?: string
  }) => api.post<TokenPayload>('/auth/register', payload),
  me: () => api.get<User>('/auth/me'),
  changePassword: (old_password: string, new_password: string) =>
    api.post<null>('/auth/change-password', { old_password, new_password }),
}

export const courseApi = {
  list: () => api.get<Course[]>('/courses'),
  create: (payload: { code: string; name: string; description?: string }) =>
    api.post<Course>('/courses', payload),
  detail: (id: number) => api.get<Course>(`/courses/${id}`),
  update: (id: number, payload: { name?: string; description?: string }) =>
    api.patch<Course>(`/courses/${id}`, payload),
  members: (id: number) => api.get<Member[]>(`/courses/${id}/members`),
  addMembers: (id: number, usernames: string[]) =>
    api.post<Member[]>(`/courses/${id}/members`, { usernames }),
  kpTree: (id: number) => api.get<KnowledgePoint[]>(`/courses/${id}/knowledge-points`),
  createKp: (id: number, payload: { name: string; parent_id?: number | null; importance?: number }) =>
    api.post<KnowledgePoint>(`/courses/${id}/knowledge-points`, payload),
  autoKp: (id: number, max_points = 12) =>
    api.post<KnowledgePoint[]>(`/courses/${id}/knowledge-points:auto`, { max_points }),
  deleteKp: (kpId: number) => api.delete<null>(`/knowledge-points/${kpId}`),
  overview: (id: number) => api.get<Overview>(`/courses/${id}/stats/overview`),
  errorHeatmap: (id: number) => api.get<ErrorHeatCell[]>(`/courses/${id}/stats/error-heatmap`),
  jobs: (id: number) => api.get<Job[]>(`/courses/${id}/jobs`),
}

export const docApi = {
  list: (courseId: number) => api.get<Doc[]>(`/courses/${courseId}/documents`),
  upload: (courseId: number, file: File) =>
    api.upload<{ document_id: number; job_id?: string | null; duplicated: boolean; message: string }>(
      `/courses/${courseId}/documents`,
      file,
    ),
  detail: (id: number) => api.get<Doc>(`/documents/${id}`),
  chunks: (id: number, params: { page?: number; size?: number; q?: string; around?: number }) =>
    api.get<ChunkPage>(`/documents/${id}/chunks`, params),
  remove: (id: number) => api.delete<null>(`/documents/${id}`),
  reparse: (id: number) =>
    api.post<{ document_id: number; job_id?: string | null; message: string }>(`/documents/${id}/reparse`),
  search: (courseId: number, query: string, top_k = 6) =>
    api.post<{ query: string; count: number; items: RetrievedChunk[] }>(`/courses/${courseId}/search`, {
      query,
      top_k,
    }),
}

export const questionApi = {
  list: (
    courseId: number,
    params: { page?: number; size?: number; status?: string; type?: string; kp_id?: number } = {},
  ) => api.get<QuestionPage>(`/courses/${courseId}/questions`, params),
  detail: (id: number) => api.get<Question>(`/questions/${id}`),
  reviewQueue: (courseId: number) =>
    api.get<{ items: Question[]; total: number }>(`/courses/${courseId}/questions/review-queue`),
  generate: (
    courseId: number,
    payload: {
      course_id: number
      kp_ids: number[]
      types: Record<string, number>
      difficulty?: Record<string, number>
      requirements?: string
      auto_publish?: boolean
    },
  ) => api.post<{ job_id: string; estimated_seconds: number }>(
    `/courses/${courseId}/questions:generate`,
    payload,
  ),
  update: (id: number, payload: Partial<Pick<Question, 'stem' | 'options' | 'answer' | 'rubric' | 'explanation' | 'difficulty' | 'kp_ids'>>) =>
    api.patch<Question>(`/questions/${id}`, payload),
  remove: (id: number) => api.delete<null>(`/questions/${id}`),
  review: (id: number, action: 'approve' | 'reject', note?: string) =>
    api.post<Question>(`/questions/${id}:review`, { action, note }),
  batchReview: (ids: number[], action: 'approve' | 'reject', note?: string) =>
    api.post<{ updated: number }>('/questions:batch-review', { ids, action, note }),
}

export const paperApi = {
  list: (courseId: number) => api.get<PaperListItem[]>(`/papers`, { course_id: courseId }),
  create: (payload: {
    course_id: number
    title: string
    description?: string
    mode: 'manual' | 'auto'
    question_ids?: number[]
    config?: Record<string, unknown>
    duration_min?: number
    total_score?: number
  }) => api.post<Paper>('/papers', payload),
  detail: (id: number) => api.get<Paper>(`/papers/${id}`),
  forStudent: (id: number) => api.get<Paper>(`/papers/${id}/for-student`),
  publish: (id: number) => api.post<Paper>(`/papers/${id}:publish`),
  stats: (id: number) => api.get<PaperStats>(`/papers/${id}/stats`),
}

export const attemptApi = {
  start: (paperId: number) => api.post<Attempt>(`/papers/${paperId}/attempts`),
  detail: (id: number) => api.get<Attempt>(`/attempts/${id}`),
  saveAnswer: (attemptId: number, questionId: number, value: unknown, flagged = false) =>
    api.put<null>(`/attempts/${attemptId}/answers/${questionId}`, { value, flagged }),
  submit: (id: number) =>
    api.post<{ attempt_id: number; status: string; job_id?: string | null }>(`/attempts/${id}:submit`),
  report: (id: number) => api.get<AttemptReport>(`/attempts/${id}/report`),
  gradingStatus: (id: number) => api.get<GradingStatus>(`/attempts/${id}/grading-status`),
  kpMastery: (id: number) => api.get<KPMastery[]>(`/attempts/${id}/stats/kp-mastery`),
  mine: () => api.get<Attempt[]>(`/me/attempts`),
}

export const tutorApi = {
  list: () => api.get<TutorSession[]>('/tutor/sessions'),
  create: (payload: { course_id?: number; question_id?: number; answer_id?: number }) =>
    api.post<TutorOpening>('/tutor/sessions', payload),
  detail: (id: number) => api.get<TutorSessionDetail>(`/tutor/sessions/${id}`),
  remove: (id: number) => api.delete<null>(`/tutor/sessions/${id}`),
}

export const jobApi = {
  get: (taskId: string) => api.get<Job>(`/jobs/${taskId}`),
  retry: (taskId: string) => api.post<Job>(`/jobs/${taskId}:retry`),
}
