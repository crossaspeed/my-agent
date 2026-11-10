import { BulbOutlined, CheckCircleTwoTone, CloseCircleTwoTone } from '@ant-design/icons'
import {
  Alert,
  App,
  Button,
  Card,
  Col,
  Collapse,
  Descriptions,
  Progress,
  Row,
  Space,
  Spin,
  Statistic,
  Tag,
  Typography,
} from 'antd'
import { useMutation, useQuery } from '@tanstack/react-query'
import { useNavigate, useParams } from 'react-router-dom'
import { errorText } from '@/api/client'
import { attemptApi, tutorApi } from '@/api/endpoints'
import type { ReportItem } from '@/api/types'
import CitationCard from '@/components/CitationCard'
import EmptyState from '@/components/EmptyState'
import MarkdownView from '@/components/MarkdownView'
import ScoreRadar from '@/components/ScoreRadar'

const TYPE_LABEL: Record<string, string> = {
  single: '单选',
  multiple: '多选',
  judge: '判断',
  short: '简答',
  essay: '论述',
}

function renderAnswer(value: unknown): string {
  if (value === null || value === undefined || value === '') return '（未作答）'
  if (typeof value === 'boolean') return value ? '正确' : '错误'
  if (Array.isArray(value)) return value.length ? value.join('、') : '（未作答）'
  return String(value)
}

export default function ReportPage() {
  const { attemptId } = useParams()
  const id = Number(attemptId)
  const navigate = useNavigate()
  const { message } = App.useApp()

  const { data: status } = useQuery({
    queryKey: ['grading-status', id],
    queryFn: () => attemptApi.gradingStatus(id),
    enabled: Number.isFinite(id),
    refetchInterval: (query) => (query.state.data?.status === 'submitted' ? 1500 : false),
  })

  const { data: report, isLoading } = useQuery({
    queryKey: ['report', id, status?.status],
    queryFn: () => attemptApi.report(id),
    enabled: Number.isFinite(id),
  })

  const tutorMutation = useMutation({
    mutationFn: (item: ReportItem) =>
      tutorApi.create({ question_id: item.question_id, course_id: report?.course_id }),
    onSuccess: (opening) => navigate(`/tutor/${opening.session_id}`),
    onError: (error) => message.error(errorText(error)),
  })

  if (isLoading || !report) {
    return (
      <div style={{ textAlign: 'center', paddingTop: 120 }}>
        <Spin size="large" />
      </div>
    )
  }

  const grading = status?.status === 'submitted'
  const rate = Math.round((report.score_rate ?? 0) * 100)

  return (
    <div className="page">
      <Space direction="vertical" size={16} style={{ width: '100%' }}>
        <Card>
          <Row gutter={24} align="middle">
            <Col xs={24} md={8}>
              <Statistic
                title={report.paper_title}
                value={report.total_score}
                suffix={`/ ${report.max_score}`}
                precision={1}
                valueStyle={{ fontSize: 40, color: rate >= 60 ? '#cf1322' : '#3f8600' }}
              />
              <Space size={8} style={{ marginTop: 8 }}>
                <Tag color={rate >= 60 ? 'red' : 'green'}>得分率 {rate}%</Tag>
                {report.duration_seconds != null && (
                  <Tag>用时 {Math.round(report.duration_seconds / 60)} 分钟</Tag>
                )}
                {report.needs_human_count > 0 && <Tag color="orange">{report.needs_human_count} 题待人工复核</Tag>}
              </Space>
            </Col>
            <Col xs={24} md={8}>
              <ScoreRadar
                data={report.kp_mastery.map((item) => ({ name: item.name, rate: item.rate }))}
                size={280}
              />
            </Col>
            <Col xs={24} md={8}>
              <Descriptions column={1} size="small" title="错因分布">
                {Object.keys(report.error_tag_stats ?? {}).length === 0 ? (
                  <Descriptions.Item label="—">暂无错因标签</Descriptions.Item>
                ) : (
                  Object.entries(report.error_tag_stats)
                    .sort((a, b) => b[1] - a[1])
                    .map(([tag, count]) => (
                      <Descriptions.Item key={tag} label={tag}>
                        <Progress percent={Math.min(100, count * 20)} steps={5} size="small" />
                      </Descriptions.Item>
                    ))
                )}
              </Descriptions>
            </Col>
          </Row>
        </Card>

        {grading && (
          <Alert
            type="info"
            showIcon
            message="阅卷中"
            description={`已完成 ${status?.graded ?? 0} / ${status?.total ?? 0} 题，页面会自动刷新结果。`}
          />
        )}

        <Card title="逐题解析" size="small">
          {report.items.length === 0 ? (
            <EmptyState description="暂无作答明细" />
          ) : (
            <Collapse
              accordion
              items={report.items.map((item) => {
                const correct = item.is_correct === true
                return {
                  key: String(item.question_id),
                  label: (
                    <Space size={8} wrap>
                      {item.is_correct === null || item.is_correct === undefined ? (
                        <Tag color="orange">待复核</Tag>
                      ) : correct ? (
                        <CheckCircleTwoTone twoToneColor="#52c41a" />
                      ) : (
                        <CloseCircleTwoTone twoToneColor="#ff4d4f" />
                      )}
                      <Tag>第 {item.seq} 题</Tag>
                      <Tag>{TYPE_LABEL[item.type] ?? item.type}</Tag>
                      <Typography.Text ellipsis style={{ maxWidth: 520 }}>
                        {item.stem}
                      </Typography.Text>
                      <Tag color={item.score >= item.max_score ? 'green' : 'red'}>
                        {item.score} / {item.max_score} 分
                      </Tag>
                      {item.needs_human && <Tag color="orange">低置信·待人工</Tag>}
                    </Space>
                  ),
                  children: (
                    <Space direction="vertical" size={12} style={{ width: '100%' }}>
                      <Descriptions column={1} size="small" bordered>
                        <Descriptions.Item label="我的答案">{renderAnswer(item.student_answer)}</Descriptions.Item>
                        {item.type !== 'short' && item.type !== 'essay' && (
                          <Descriptions.Item label="参考答案">{renderAnswer(item.correct_answer)}</Descriptions.Item>
                        )}
                        {item.graded_by && (
                          <Descriptions.Item label="评分方式">
                            {item.graded_by === 'rule' ? '规则判分（客观题）' : '智能体评分'}
                          </Descriptions.Item>
                        )}
                      </Descriptions>

                      {item.rubric_detail?.length > 0 && (
                        <Space direction="vertical" size={4}>
                          <Typography.Text strong>评分要点命中</Typography.Text>
                          {item.rubric_detail.map((detail, i) => (
                            <Space key={i} size={6}>
                              {detail.hit ? (
                                <CheckCircleTwoTone twoToneColor="#52c41a" />
                              ) : (
                                <CloseCircleTwoTone twoToneColor="#d9d9d9" />
                              )}
                              <Typography.Text delete={!detail.hit}>{detail.point}</Typography.Text>
                              <Tag>{detail.score ?? 0} 分</Tag>
                            </Space>
                          ))}
                        </Space>
                      )}

                      {item.feedback && (
                        <div>
                          <Typography.Text strong>阅卷反馈</Typography.Text>
                          <MarkdownView text={item.feedback} />
                        </div>
                      )}

                      {item.error_tags?.length > 0 && (
                        <Space size={6} wrap>
                          <Typography.Text type="secondary">错因标签：</Typography.Text>
                          {item.error_tags.map((tag) => (
                            <Tag key={tag} color="volcano">
                              {tag}
                            </Tag>
                          ))}
                        </Space>
                      )}

                      {item.source_refs?.length > 0 && (
                        <div>
                          <Typography.Text strong>溯源原文</Typography.Text>
                          {item.source_refs.map((sourceRef, i) => (
                            <CitationCard
                              key={`${sourceRef.chunk_id}-${i}`}
                              refItem={sourceRef}
                              index={i}
                              compact
                            />
                          ))}
                        </div>
                      )}

                      <Button
                        icon={<BulbOutlined />}
                        type="primary"
                        ghost
                        loading={tutorMutation.isPending}
                        onClick={() => tutorMutation.mutate(item)}
                      >
                        让 AI 导学讲清这道题
                      </Button>
                    </Space>
                  ),
                }
              })}
            />
          )}
        </Card>

        <Space>
          <Button onClick={() => navigate('/attempts')}>返回我的测评</Button>
          <Button type="primary" onClick={() => navigate('/tutor')}>
            进入 AI 导学
          </Button>
        </Space>
      </Space>
    </div>
  )
}
