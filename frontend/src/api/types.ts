// 与后端 app/schemas 一一对应的类型定义（手工维护，字段名不得随意改动）

export interface Envelope<T> {
  code: number
  message: string
  data: T
}

export interface User {
  id: number
  username: string
  email?: string | null
  real_name?: string | null
  role: 'admin' | 'teacher' | 'student'
  is_active: boolean
  created_at?: string | null
}

export interface TokenPayload {
  access_token: string
  token_type: string
  expires_in: number
  user: User
}

export interface CourseStats {
  documents: number
  questions: number
  papers: number
  students: number
  knowledge_points: number
  chunks: number
}

export interface Course {
  id: number
  code: string
  name: string
  description?: string | null
  owner_id: number
  settings: Record<string, unknown>
  created_at?: string | null
  my_role: 'owner' | 'teacher' | 'student'
  stats: CourseStats
}

export interface KnowledgePoint {
  id: number
  course_id: number
  parent_id?: number | null
  name: string
  description?: string | null
  importance: number
  sort_order: number
  children: KnowledgePoint[]
  chunk_count: number
}

export interface Member {
  user_id: number
  username: string
  real_name?: string | null
  role: string
}

export type DocStatus = 'pending' | 'parsing' | 'ready' | 'failed'

export interface Doc {
  id: number
  course_id: number
  filename: string
  file_type: string
  size_bytes: number
  status: DocStatus
  error_msg?: string | null
  page_count?: number | null
  chunk_count: number
  meta: Record<string, unknown>
  created_at?: string | null
  job_id?: string | null
}

export interface Chunk {
  id: number
  document_id: number
  chunk_index: number
  content: string
  page_no?: number | null
  slide_no?: number | null
  heading_path?: string | null
  token_count?: number | null
  document_name?: string | null
}

export interface ChunkPage {
  items: Chunk[]
  total: number
  page: number
  size: number
  highlight_id?: number | null
}

export interface RetrievedChunk {
  chunk_id: number
  content: string
  score: number
  source: string
  page_no?: number | null
  heading_path?: string | null
  document_id?: number | null
  document_name?: string | null
}

export interface SourceRef {
  chunk_id: number
  document_id?: number | null
  document_name?: string | null
  page_no?: number | null
  slide_no?: number | null
  heading_path?: string | null
  quote: string
  score: number
}

export interface CitationQuality {
  citation_ok: boolean
  citation_fix_count: number
  quote_match_ratio: number
  answer_supported?: boolean | null
  duplicated?: boolean
  warnings?: string[]
}

export type QuestionType = 'single' | 'multiple' | 'judge' | 'short' | 'essay'

export interface QuestionOption {
  key: string
  text: string
}

export interface RubricItem {
  point: string
  score: number
}

export interface Question {
  id: number
  course_id: number
  type: QuestionType
  stem: string
  options?: QuestionOption[] | null
  answer?: unknown
  rubric: RubricItem[]
  explanation?: string | null
  difficulty: number
  source_refs: SourceRef[]
  kp_ids: number[]
  status: 'draft' | 'pending' | 'published' | 'rejected' | 'archived'
  quality?: CitationQuality | null
  gen_meta?: Record<string, unknown> | null
  review_note?: string | null
  created_at?: string | null
}

export interface QuestionPage {
  items: Question[]
  total: number
  page: number
  size: number
}

export interface PaperQuestion {
  question_id: number
  seq: number
  score: number
  question: Question
}

export interface PaperListItem {
  id: number
  course_id: number
  title: string
  description?: string | null
  total_score: number
  duration_min: number
  status: 'draft' | 'published' | 'closed'
  created_at?: string | null
  question_count: number
  attempt_id?: number | null
  attempt_status?: string | null
  my_score?: number | null
}

export interface Paper {
  id: number
  course_id: number
  creator_id: number
  title: string
  description?: string | null
  config: Record<string, unknown>
  total_score: number
  duration_min: number
  status: 'draft' | 'published' | 'closed'
  start_at?: string | null
  end_at?: string | null
  created_at?: string | null
  questions: PaperQuestion[]
  attempt_id?: number | null
  attempt_status?: string | null
}

export interface AnswerDraft {
  question_id: number
  seq: number
  type: QuestionType
  stem: string
  options?: QuestionOption[] | null
  score: number
  value: unknown
  flagged: boolean
}

export interface Attempt {
  id: number
  paper_id: number
  student_id: number
  status: 'in_progress' | 'submitted' | 'graded'
  total_score?: number | null
  max_score?: number | null
  started_at?: string | null
  submitted_at?: string | null
  graded_at?: string | null
  paper_title?: string | null
  duration_min: number
  answers: AnswerDraft[]
}

export interface GradingStatus {
  attempt_id: number
  status: string
  graded: number
  total: number
  progress: number
  job_id?: string | null
}

export interface ReportItem {
  seq: number
  question_id: number
  type: QuestionType
  stem: string
  options?: QuestionOption[] | null
  student_answer: unknown
  correct_answer: unknown
  is_correct?: boolean | null
  score: number
  max_score: number
  rubric_detail: { point?: string; hit?: boolean; score?: number }[]
  feedback?: string | null
  error_tags: string[]
  needs_human: boolean
  graded_by?: string | null
  source_refs: SourceRef[]
}

export interface KPMastery {
  kp_id: number
  name: string
  total_score: number
  earned_score: number
  rate: number
  question_count: number
  wrong_count: number
}

export interface AttemptReport {
  attempt_id: number
  paper_id: number
  course_id: number
  paper_title: string
  student_id: number
  status: string
  total_score: number
  max_score: number
  score_rate: number
  duration_seconds?: number | null
  items: ReportItem[]
  kp_mastery: KPMastery[]
  wrong_items: ReportItem[]
  error_tag_stats: Record<string, number>
  needs_human_count: number
}

export interface TutorMessage {
  id: number
  session_id: number
  role: 'user' | 'assistant' | 'system'
  content: string
  refs: SourceRef[]
  meta?: Record<string, unknown> | null
  created_at?: string | null
}

export interface TutorSession {
  id: number
  student_id: number
  course_id: number
  answer_id?: number | null
  question_id?: number | null
  title?: string | null
  summary?: string | null
  created_at?: string | null
  last_active_at?: string | null
  message_count: number
  last_message?: string | null
}

export interface TutorSessionDetail extends TutorSession {
  messages: TutorMessage[]
  practice: Record<string, unknown>[]
}

export interface TutorOpening {
  session_id: number
  message: TutorMessage
  refs: SourceRef[]
  practice: Record<string, unknown>[]
}

export interface Job {
  task_id: string
  job_type: string
  target_id?: number | null
  course_id?: number | null
  status: 'pending' | 'running' | 'succeeded' | 'failed'
  progress: number
  stage?: string | null
  result?: Record<string, unknown> | null
  error_msg?: string | null
  created_at?: string | null
  finished_at?: string | null
}

export interface Overview {
  documents: number
  chunks: number
  questions: number
  published_questions: number
  papers: number
  students: number
  attempts: number
  avg_score: number
  knowledge_points: number
  recent_jobs: Record<string, unknown>[]
}

export interface ErrorHeatCell {
  kp_id: number
  kp_name: string
  total: number
  wrong: number
  rate: number
  tags: Record<string, number>
}

export interface PaperStats {
  paper_id: number
  title: string
  submitted: number
  avg_score: number
  max_score: number
  min_score: number
  items: {
    student_id?: number
    username?: string
    total_score?: number
    status?: string
    [key: string]: unknown
  }[]
}

export interface SSEHandlers {
  onMeta?: (data: { session_id: number; message_id: number }) => void
  onToken?: (delta: string) => void
  onRefs?: (data: { refs: SourceRef[]; practice: Record<string, unknown>[]; diagnosis?: string }) => void
  onDone?: (data: { message_id: number; content: string; refs: SourceRef[] }) => void
  onError?: (data: { code: number; message: string; partial?: string }) => void
}
