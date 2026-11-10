import { DeleteOutlined, PlusOutlined, SendOutlined } from '@ant-design/icons'
import {
  App,
  Button,
  Card,
  Col,
  Empty,
  Input,
  List,
  Modal,
  Popconfirm,
  Row,
  Select,
  Space,
  Spin,
  Tag,
  Typography,
} from 'antd'
import { useEffect, useMemo, useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useNavigate, useParams } from 'react-router-dom'
import { errorText } from '@/api/client'
import { courseApi, questionApi, tutorApi } from '@/api/endpoints'
import type { SourceRef, TutorMessage } from '@/api/types'
import MarkdownView from '@/components/MarkdownView'
import SourceDrawer from '@/components/SourceDrawer'
import { useSSEStream } from '@/hooks/useSSE'

export default function TutorPage() {
  const { sessionId } = useParams()
  const activeId = sessionId ? Number(sessionId) : null
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const { message } = App.useApp()
  const { send, abort } = useSSEStream()

  const [input, setInput] = useState('')
  const [streaming, setStreaming] = useState(false)
  const [streamText, setStreamText] = useState('')
  const [pendingUser, setPendingUser] = useState<string | null>(null)
  const [refs, setRefs] = useState<SourceRef[] | null>(null)
  const [createOpen, setCreateOpen] = useState(false)
  const [courseId, setCourseId] = useState<number | undefined>()
  const [questionId, setQuestionId] = useState<number | undefined>()
  const bottomRef = useRef<HTMLDivElement | null>(null)

  const { data: sessions } = useQuery({ queryKey: ['tutor-sessions'], queryFn: tutorApi.list })
  const { data: detail, isLoading: detailLoading } = useQuery({
    queryKey: ['tutor-session', activeId],
    queryFn: () => tutorApi.detail(activeId as number),
    enabled: Boolean(activeId),
  })
  const { data: courses } = useQuery({ queryKey: ['courses'], queryFn: courseApi.list, enabled: createOpen })
  const { data: questions } = useQuery({
    queryKey: ['course-questions-for-tutor', courseId],
    queryFn: () => questionApi.list(courseId as number, { page: 1, size: 50, status: 'published' }),
    enabled: Boolean(courseId),
  })

  const createMutation = useMutation({
    mutationFn: () => tutorApi.create({ course_id: courseId, question_id: questionId }),
    onSuccess: (opening) => {
      setCreateOpen(false)
      void queryClient.invalidateQueries({ queryKey: ['tutor-sessions'] })
      navigate(`/tutor/${opening.session_id}`)
    },
    onError: (error) => message.error(errorText(error)),
  })

  const deleteMutation = useMutation({
    mutationFn: (id: number) => tutorApi.remove(id),
    onSuccess: () => {
      message.success('会话已删除')
      void queryClient.invalidateQueries({ queryKey: ['tutor-sessions'] })
      navigate('/tutor')
    },
    onError: (error) => message.error(errorText(error)),
  })

  const messages: TutorMessage[] = useMemo(() => detail?.messages ?? [], [detail])

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages.length, streamText])

  useEffect(() => () => abort(), [abort])

  const onSend = async () => {
    const content = input.trim()
    if (!content || !activeId || streaming) return
    setInput('')
    setPendingUser(content)
    setStreamText('')
    setStreaming(true)
    await send(activeId, content, {
      onMeta: () => setPendingUser(content),
      onToken: (delta) => setStreamText((prev) => prev + delta),
      onRefs: (data) => setRefs(data.refs ?? []),
      onDone: () => {
        setStreaming(false)
        setPendingUser(null)
        setStreamText('')
        void queryClient.invalidateQueries({ queryKey: ['tutor-session', activeId] })
        void queryClient.invalidateQueries({ queryKey: ['tutor-sessions'] })
      },
      onError: (data) => {
        setStreaming(false)
        setPendingUser(null)
        message.error(data.message || '讲解生成失败')
      },
    })
  }

  return (
    <div className="page">
      <Row gutter={16}>
        <Col xs={24} lg={6}>
          <Card
            size="small"
            title="导学会话"
            extra={
              <Button size="small" type="primary" icon={<PlusOutlined />} onClick={() => setCreateOpen(true)}>
                新建
              </Button>
            }
            styles={{ body: { padding: 0 } }}
          >
            {sessions?.length ? (
              <List
                size="small"
                dataSource={sessions}
                renderItem={(item) => (
                  <List.Item
                    className={item.id === activeId ? 'tutor-item active' : 'tutor-item'}
                    onClick={() => navigate(`/tutor/${item.id}`)}
                    actions={[
                      <Popconfirm
                        key="del"
                        title="删除该会话？"
                        onConfirm={(e) => {
                          e?.stopPropagation()
                          deleteMutation.mutate(item.id)
                        }}
                      >
                        <Button
                          type="text"
                          size="small"
                          danger
                          icon={<DeleteOutlined />}
                          onClick={(e) => e.stopPropagation()}
                        />
                      </Popconfirm>,
                    ]}
                  >
                    <List.Item.Meta
                      title={<Typography.Text ellipsis>{item.title ?? '导学会话'}</Typography.Text>}
                      description={
                        <Typography.Text type="secondary" ellipsis style={{ fontSize: 12 }}>
                          {item.last_message ?? `${item.message_count} 条消息`}
                        </Typography.Text>
                      }
                    />
                  </List.Item>
                )}
              />
            ) : (
              <Empty description="还没有导学会话" image={Empty.PRESENTED_IMAGE_SIMPLE} style={{ padding: 24 }} />
            )}
          </Card>
        </Col>

        <Col xs={24} lg={18}>
          <Card
            size="small"
            title={
              detail ? (
                <Space>
                  <span>{detail.title ?? 'AI 导学'}</span>
                  {detail.practice?.length ? <Tag color="cyan">{detail.practice.length} 个推荐练习</Tag> : null}
                </Space>
              ) : (
                'AI 导学'
              )
            }
            extra={
              refs?.length ? (
                <Button type="link" size="small" onClick={() => setRefs(refs)}>
                  查看引用溯源（{refs.length}）
                </Button>
              ) : null
            }
            styles={{ body: { minHeight: 520, display: 'flex', flexDirection: 'column' } }}
          >
            {!activeId ? (
              <Empty
                description="选择左侧会话，或从测评报告里点「让 AI 导学讲清这道题」开始一次针对性讲解"
                style={{ margin: 'auto' }}
              />
            ) : detailLoading ? (
              <Spin style={{ margin: 'auto' }} />
            ) : (
              <>
                <div className="chat-scroll">
                  {messages.map((msgItem) => (
                    <div key={msgItem.id} className={`chat-bubble ${msgItem.role === 'user' ? 'user' : 'assistant'}`}>
                      <div className="chat-meta">
                        <Tag color={msgItem.role === 'user' ? 'default' : 'blue'}>
                          {msgItem.role === 'user' ? '我' : '导学师'}
                        </Tag>
                        {msgItem.refs?.length ? (
                          <Button type="link" size="small" onClick={() => setRefs(msgItem.refs)}>
                            {msgItem.refs.length} 条溯源
                          </Button>
                        ) : null}
                      </div>
                      {msgItem.role === 'user' ? (
                        <Typography.Paragraph style={{ marginBottom: 0, whiteSpace: 'pre-wrap' }}>
                          {msgItem.content}
                        </Typography.Paragraph>
                      ) : (
                        <MarkdownView text={msgItem.content} />
                      )}
                    </div>
                  ))}

                  {pendingUser && (
                    <div className="chat-bubble user">
                      <div className="chat-meta">
                        <Tag>我</Tag>
                      </div>
                      <Typography.Paragraph style={{ marginBottom: 0, whiteSpace: 'pre-wrap' }}>
                        {pendingUser}
                      </Typography.Paragraph>
                    </div>
                  )}

                  {streaming && (
                    <div className="chat-bubble assistant">
                      <div className="chat-meta">
                        <Tag color="blue">导学师</Tag>
                        {!streamText && <Typography.Text type="secondary">正在检索课件原文…</Typography.Text>}
                      </div>
                      {streamText && <MarkdownView text={streamText} />}
                    </div>
                  )}
                  <div ref={bottomRef} />
                </div>

                <Space.Compact style={{ width: '100%', marginTop: 12 }}>
                  <Input.TextArea
                    autoSize={{ minRows: 1, maxRows: 4 }}
                    placeholder="继续追问，例如：为什么拥塞控制要分四个阶段？"
                    value={input}
                    onChange={(e) => setInput(e.target.value)}
                    onPressEnter={(e) => {
                      if (!e.shiftKey) {
                        e.preventDefault()
                        void onSend()
                      }
                    }}
                  />
                  <Button type="primary" icon={<SendOutlined />} loading={streaming} onClick={() => void onSend()}>
                    发送
                  </Button>
                </Space.Compact>
              </>
            )}
          </Card>
        </Col>
      </Row>

      <SourceDrawer open={refs !== null} refs={refs ?? []} onClose={() => setRefs(null)} title="讲解引用原文" />

      <Modal
        title="开始新的导学"
        open={createOpen}
        onCancel={() => setCreateOpen(false)}
        onOk={() => createMutation.mutate()}
        confirmLoading={createMutation.isPending}
        okText="开始讲解"
        okButtonProps={{ disabled: !courseId || !questionId }}
      >
        <Space direction="vertical" size={12} style={{ width: '100%' }}>
          <Select
            style={{ width: '100%' }}
            placeholder="选择课程"
            value={courseId}
            onChange={(value) => {
              setCourseId(value)
              setQuestionId(undefined)
            }}
            options={(courses ?? []).map((course) => ({ value: course.id, label: course.name }))}
          />
          <Select
            style={{ width: '100%' }}
            placeholder={courseId ? '选择要讲解的题目' : '请先选择课程'}
            disabled={!courseId}
            value={questionId}
            onChange={setQuestionId}
            showSearch
            optionFilterProp="label"
            options={(questions?.items ?? []).map((question) => ({
              value: question.id,
              label: question.stem.slice(0, 60),
            }))}
          />
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
            导学师会先定位该题对应的课件原文，再分层讲解并给出练习建议；讲解中所有结论均附原文引用。
          </Typography.Text>
        </Space>
      </Modal>
    </div>
  )
}
