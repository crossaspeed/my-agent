import { FlagOutlined, LeftOutlined, RightOutlined } from '@ant-design/icons'
import {
  App,
  Button,
  Card,
  Checkbox,
  Col,
  Input,
  Radio,
  Row,
  Space,
  Spin,
  Switch,
  Tag,
  Typography,
} from 'antd'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useMutation, useQuery } from '@tanstack/react-query'
import { useNavigate, useParams } from 'react-router-dom'
import { errorText } from '@/api/client'
import { attemptApi } from '@/api/endpoints'
import type { AnswerDraft } from '@/api/types'
import ExamTimer from '@/components/ExamTimer'

const TYPE_LABEL: Record<string, string> = {
  single: '单选',
  multiple: '多选',
  judge: '判断',
  short: '简答',
  essay: '论述',
}

export default function ExamPage() {
  const { attemptId } = useParams()
  const id = Number(attemptId)
  const navigate = useNavigate()
  const { message, modal } = App.useApp()
  const [index, setIndex] = useState(0)
  const [values, setValues] = useState<Record<number, unknown>>({})
  const [flags, setFlags] = useState<Record<number, boolean>>({})
  const timers = useRef<Record<number, number>>({})

  const { data: attempt, isLoading } = useQuery({
    queryKey: ['attempt', id],
    queryFn: () => attemptApi.detail(id),
    enabled: Number.isFinite(id),
  })

  useEffect(() => {
    if (!attempt) return
    const initial: Record<number, unknown> = {}
    const initFlags: Record<number, boolean> = {}
    for (const answer of attempt.answers) {
      initial[answer.question_id] = answer.value
      initFlags[answer.question_id] = answer.flagged
    }
    setValues(initial)
    setFlags(initFlags)
    if (attempt.status !== 'in_progress') {
      navigate(`/report/${attempt.id}`, { replace: true })
    }
  }, [attempt, navigate])

  const saveMutation = useMutation({
    mutationFn: ({ questionId, value, flagged }: { questionId: number; value: unknown; flagged: boolean }) =>
      attemptApi.saveAnswer(id, questionId, value, flagged),
    onError: (error) => message.error(`草稿保存失败：${errorText(error)}`),
  })

  const submitMutation = useMutation({
    mutationFn: () => attemptApi.submit(id),
    onSuccess: () => {
      message.success('已交卷，阅卷官正在批阅')
      navigate(`/report/${id}`, { replace: true })
    },
    onError: (error) => message.error(errorText(error)),
  })

  const persist = useCallback(
    (questionId: number, value: unknown, flagged: boolean) => {
      window.clearTimeout(timers.current[questionId])
      timers.current[questionId] = window.setTimeout(() => {
        saveMutation.mutate({ questionId, value, flagged })
      }, 600)
    },
    [saveMutation],
  )

  const answers = useMemo(() => attempt?.answers ?? [], [attempt])
  const current: AnswerDraft | undefined = answers[index]

  const setValue = (questionId: number, value: unknown) => {
    setValues((prev) => ({ ...prev, [questionId]: value }))
    persist(questionId, value, flags[questionId] ?? false)
  }

  const toggleFlag = (questionId: number, flagged: boolean) => {
    setFlags((prev) => ({ ...prev, [questionId]: flagged }))
    persist(questionId, values[questionId], flagged)
  }

  const answeredCount = answers.filter((a) => {
    const value = values[a.question_id]
    if (Array.isArray(value)) return value.length > 0
    return value !== undefined && value !== null && value !== ''
  }).length

  const doSubmit = () => {
    modal.confirm({
      title: '确认交卷？',
      content: `已作答 ${answeredCount} / ${answers.length} 题，交卷后不可修改。`,
      okText: '交卷',
      cancelText: '继续作答',
      onOk: () => submitMutation.mutate(),
    })
  }

  if (isLoading || !attempt) {
    return (
      <div style={{ textAlign: 'center', paddingTop: 120 }}>
        <Spin size="large" />
      </div>
    )
  }

  return (
    <div className="exam-page">
      <Card size="small" className="exam-header">
        <Row align="middle" justify="space-between" gutter={12}>
          <Col>
            <Space size={12}>
              <Typography.Text strong style={{ fontSize: 16 }}>
                {attempt.paper_title ?? '在线测评'}
              </Typography.Text>
              <Tag>共 {answers.length} 题</Tag>
              <Tag color="blue">
                已答 {answeredCount}/{answers.length}
              </Tag>
            </Space>
          </Col>
          <Col>
            <Space size={12}>
              <ExamTimer startedAt={attempt.started_at} durationMin={attempt.duration_min} onExpire={doSubmit} />
              <Button type="primary" loading={submitMutation.isPending} onClick={doSubmit}>
                交卷
              </Button>
            </Space>
          </Col>
        </Row>
      </Card>

      <Row gutter={16} style={{ marginTop: 16 }}>
        <Col xs={24} lg={5}>
          <Card size="small" title="答题卡">
            <div className="answer-sheet">
              {answers.map((answer, i) => {
                const value = values[answer.question_id]
                const answered = Array.isArray(value)
                  ? value.length > 0
                  : value !== undefined && value !== null && value !== ''
                return (
                  <button
                    key={answer.question_id}
                    type="button"
                    className={[
                      'answer-dot',
                      i === index ? 'active' : '',
                      answered ? 'answered' : '',
                      flags[answer.question_id] ? 'flagged' : '',
                    ].join(' ')}
                    onClick={() => setIndex(i)}
                  >
                    {answer.seq}
                  </button>
                )
              })}
            </div>
            <Typography.Paragraph type="secondary" style={{ fontSize: 12, marginTop: 12, marginBottom: 0 }}>
              蓝色=已作答，橙色边框=已标记待回看。作答自动保存，刷新不丢草稿。
            </Typography.Paragraph>
          </Card>
        </Col>

        <Col xs={24} lg={19}>
          {current && (
            <Card
              title={
                <Space size={8} wrap>
                  <Tag color="blue">第 {current.seq} 题</Tag>
                  <Tag>{TYPE_LABEL[current.type] ?? current.type}</Tag>
                  <Tag color="gold">{current.score} 分</Tag>
                </Space>
              }
              extra={
                <Space size={6}>
                  <FlagOutlined style={{ color: flags[current.question_id] ? '#fa8c16' : undefined }} />
                  <Switch
                    size="small"
                    checked={flags[current.question_id] ?? false}
                    onChange={(checked) => toggleFlag(current.question_id, checked)}
                  />
                  <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                    标记
                  </Typography.Text>
                </Space>
              }
            >
              <Typography.Paragraph style={{ fontSize: 15, whiteSpace: 'pre-wrap' }}>
                {current.stem}
              </Typography.Paragraph>

              <div style={{ marginTop: 8 }}>
                {current.type === 'single' && (
                  <Radio.Group
                    style={{ display: 'flex', flexDirection: 'column', gap: 12 }}
                    value={values[current.question_id] as string | undefined}
                    onChange={(e) => setValue(current.question_id, e.target.value)}
                  >
                    {(current.options ?? []).map((option) => (
                      <Radio key={option.key} value={option.key}>
                        <Typography.Text strong>{option.key}.</Typography.Text> {option.text}
                      </Radio>
                    ))}
                  </Radio.Group>
                )}

                {current.type === 'multiple' && (
                  <Checkbox.Group
                    style={{ display: 'flex', flexDirection: 'column', gap: 12 }}
                    value={(values[current.question_id] as string[] | undefined) ?? []}
                    onChange={(checked) => setValue(current.question_id, checked)}
                  >
                    {(current.options ?? []).map((option) => (
                      <Checkbox key={option.key} value={option.key}>
                        <Typography.Text strong>{option.key}.</Typography.Text> {option.text}
                      </Checkbox>
                    ))}
                  </Checkbox.Group>
                )}

                {current.type === 'judge' && (
                  <Radio.Group
                    value={values[current.question_id] as boolean | undefined}
                    onChange={(e) => setValue(current.question_id, e.target.value)}
                  >
                    <Space direction="vertical" size={12}>
                      <Radio value={true}>正确</Radio>
                      <Radio value={false}>错误</Radio>
                    </Space>
                  </Radio.Group>
                )}

                {(current.type === 'short' || current.type === 'essay') && (
                  <Input.TextArea
                    autoSize={{ minRows: 6, maxRows: 14 }}
                    placeholder="请结合课件中的概念与要点作答，评分将按要点命中给分"
                    value={(values[current.question_id] as string | undefined) ?? ''}
                    onChange={(e) => setValue(current.question_id, e.target.value)}
                  />
                )}
              </div>

              <Space style={{ marginTop: 24 }}>
                <Button icon={<LeftOutlined />} disabled={index === 0} onClick={() => setIndex((i) => i - 1)}>
                  上一题
                </Button>
                <Button
                  type="primary"
                  icon={<RightOutlined />}
                  disabled={index === answers.length - 1}
                  onClick={() => setIndex((i) => i + 1)}
                >
                  下一题
                </Button>
              </Space>
            </Card>
          )}
        </Col>
      </Row>

    </div>
  )
}
