import { DeleteOutlined, InboxOutlined, ReloadOutlined, SearchOutlined } from '@ant-design/icons'
import {
  Alert,
  App,
  Button,
  Drawer,
  Input,
  Popconfirm,
  Pagination,
  Space,
  Table,
  Tag,
  Typography,
  Upload,
} from 'antd'
import type { ColumnsType } from 'antd/es/table'
import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { errorText } from '@/api/client'
import { docApi } from '@/api/endpoints'
import type { Chunk, Doc } from '@/api/types'
import EmptyState from '@/components/EmptyState'
import TaskProgress from '@/components/TaskProgress'

interface Props {
  courseId: number
  canEdit: boolean
}

const STATUS_TAG: Record<string, { color: string; text: string }> = {
  pending: { color: 'default', text: '排队中' },
  parsing: { color: 'processing', text: '解析中' },
  ready: { color: 'success', text: '就绪' },
  failed: { color: 'error', text: '失败' },
}

export default function DocumentsTab({ courseId, canEdit }: Props) {
  const { message } = App.useApp()
  const queryClient = useQueryClient()
  const [jobId, setJobId] = useState<string | null>(null)
  const [chunkDoc, setChunkDoc] = useState<Doc | null>(null)
  const [chunkPage, setChunkPage] = useState(1)
  const [keyword, setKeyword] = useState('')

  const { data: docs, isLoading } = useQuery({
    queryKey: ['documents', courseId],
    queryFn: () => docApi.list(courseId),
    refetchInterval: (query) => {
      const list = query.state.data ?? []
      return list.some((d) => d.status === 'pending' || d.status === 'parsing') ? 2000 : false
    },
  })

  const { data: chunks } = useQuery({
    queryKey: ['chunks', chunkDoc?.id, chunkPage, keyword],
    queryFn: () => docApi.chunks(chunkDoc!.id, { page: chunkPage, size: 10, q: keyword || undefined }),
    enabled: Boolean(chunkDoc),
  })

  const uploadMutation = useMutation({
    mutationFn: (file: File) => docApi.upload(courseId, file),
    onSuccess: (result) => {
      message.success(result.duplicated ? '该文件已存在，已跳过重复解析' : result.message)
      setJobId(result.job_id ?? null)
      void queryClient.invalidateQueries({ queryKey: ['documents', courseId] })
    },
    onError: (error) => message.error(errorText(error)),
  })

  const reparseMutation = useMutation({
    mutationFn: (id: number) => docApi.reparse(id),
    onSuccess: (result) => {
      message.success('已重新排队解析')
      setJobId(result.job_id ?? null)
      void queryClient.invalidateQueries({ queryKey: ['documents', courseId] })
    },
    onError: (error) => message.error(errorText(error)),
  })

  const deleteMutation = useMutation({
    mutationFn: (id: number) => docApi.remove(id),
    onSuccess: () => {
      message.success('文档已删除（向量与分块同步清理）')
      void queryClient.invalidateQueries({ queryKey: ['documents', courseId] })
    },
    onError: (error) => message.error(errorText(error)),
  })

  const columns: ColumnsType<Doc> = [
    {
      title: '文件名',
      dataIndex: 'filename',
      render: (name: string, record) => (
        <Space direction="vertical" size={0}>
          <Typography.Text strong>{name}</Typography.Text>
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
            {(record.size_bytes / 1024).toFixed(0)} KB
            {record.page_count ? ` · ${record.page_count} 页` : ''}
          </Typography.Text>
        </Space>
      ),
    },
    {
      title: '状态',
      dataIndex: 'status',
      width: 110,
      render: (status: string, record) => (
        <Space direction="vertical" size={2}>
          <Tag color={STATUS_TAG[status]?.color}>{STATUS_TAG[status]?.text ?? status}</Tag>
          {record.error_msg && (
            <Typography.Text type="danger" style={{ fontSize: 12 }}>
              {record.error_msg}
            </Typography.Text>
          )}
        </Space>
      ),
    },
    { title: '分块', dataIndex: 'chunk_count', width: 80 },
    {
      title: '操作',
      width: 220,
      render: (_, record) => (
        <Space>
          <Button size="small" onClick={() => { setChunkDoc(record); setChunkPage(1); setKeyword('') }}>
            查看分块
          </Button>
          {canEdit && (
            <>
              <Button
                size="small"
                icon={<ReloadOutlined />}
                loading={reparseMutation.isPending}
                onClick={() => reparseMutation.mutate(record.id)}
              >
                重解析
              </Button>
              <Popconfirm
                title="删除后分块与向量将一并清理，确定删除？"
                onConfirm={() => deleteMutation.mutate(record.id)}
              >
                <Button size="small" danger icon={<DeleteOutlined />} />
              </Popconfirm>
            </>
          )}
        </Space>
      ),
    },
  ]

  return (
    <Space direction="vertical" size={16} style={{ width: '100%' }}>
      {canEdit && (
        <Upload.Dragger
          multiple={false}
          showUploadList={false}
          accept=".pdf,.pptx,.docx,.md,.txt"
          beforeUpload={(file) => {
            uploadMutation.mutate(file)
            return false
          }}
          disabled={uploadMutation.isPending}
        >
          <p className="ant-upload-drag-icon">
            <InboxOutlined />
          </p>
          <p className="ant-upload-text">点击或拖拽课件到此处上传</p>
          <p className="ant-upload-hint">
            支持 PDF / PPTX / DOCX / MD / TXT，单文件 ≤ 50MB。上传后异步解析（清洗 → 结构感知分块 → 向量化），可离开页面。
          </p>
        </Upload.Dragger>
      )}

      <TaskProgress
        taskId={jobId}
        title="课件解析"
        onDone={() => {
          message.success('解析完成，已建立检索索引')
          void queryClient.invalidateQueries({ queryKey: ['documents', courseId] })
          void queryClient.invalidateQueries({ queryKey: ['course', courseId] })
        }}
        onFail={() => void queryClient.invalidateQueries({ queryKey: ['documents', courseId] })}
      />

      {!canEdit && (
        <Alert type="info" showIcon message="课件由教师维护，你可以在题目与导学讲解中查看原文溯源" />
      )}

      <Table<Doc>
        rowKey="id"
        size="middle"
        loading={isLoading}
        columns={columns}
        dataSource={docs ?? []}
        pagination={false}
        locale={{ emptyText: <EmptyState description="还没有课件，上传后系统会自动解析并建立索引" /> }}
      />

      <Drawer
        title={`分块预览 · ${chunkDoc?.filename ?? ''}`}
        width={640}
        open={Boolean(chunkDoc)}
        onClose={() => setChunkDoc(null)}
      >
        <Space direction="vertical" size={12} style={{ width: '100%' }}>
          <Input
            allowClear
            prefix={<SearchOutlined />}
            placeholder="按关键词检索分块"
            value={keyword}
            onChange={(e) => {
              setKeyword(e.target.value)
              setChunkPage(1)
            }}
          />
          {(chunks?.items ?? []).map((chunk: Chunk) => (
            <div key={chunk.id} className="chunk-item">
              <Space size={6} wrap style={{ marginBottom: 4 }}>
                <Tag color="blue">#{chunk.chunk_index}</Tag>
                {chunk.page_no && <Tag>第 {chunk.page_no} 页</Tag>}
                {chunk.heading_path && (
                  <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                    {chunk.heading_path}
                  </Typography.Text>
                )}
                <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                  {chunk.content.length} 字
                </Typography.Text>
              </Space>
              <Typography.Paragraph style={{ marginBottom: 0, fontSize: 13, whiteSpace: 'pre-wrap' }}>
                {chunk.content}
              </Typography.Paragraph>
            </div>
          ))}
          <Pagination
            size="small"
            current={chunkPage}
            total={chunks?.total ?? 0}
            pageSize={10}
            onChange={setChunkPage}
            showSizeChanger={false}
            style={{ textAlign: 'right' }}
          />
        </Space>
      </Drawer>
    </Space>
  )
}
