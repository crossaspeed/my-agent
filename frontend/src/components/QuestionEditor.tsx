import { DeleteOutlined, PlusOutlined } from '@ant-design/icons'
import { Button, Form, Input, InputNumber, Select, Space, Tag, Typography } from 'antd'
import { useEffect } from 'react'
import type { Question, QuestionOption, RubricItem } from '@/api/types'

export interface QuestionPatch {
  stem: string
  difficulty: number
  options?: QuestionOption[]
  answer?: unknown
  rubric: RubricItem[]
  explanation?: string
}

interface FormValues {
  stem: string
  difficulty: number
  options: QuestionOption[]
  single?: string
  multiple?: string[]
  judge?: boolean
  text?: string
  rubric: RubricItem[]
  explanation?: string
}

interface Props {
  question: Question
  saving?: boolean
  onSubmit: (patch: QuestionPatch) => void
  onCancel?: () => void
}

const TYPE_LABEL: Record<string, string> = {
  single: '单选',
  multiple: '多选',
  judge: '判断',
  short: '简答',
  essay: '论述',
}

/** 题目编辑器：教师审核时修改题干/选项/答案/评分要点（客观题自动判分依赖 answer 结构） */
export default function QuestionEditor({ question, saving, onSubmit, onCancel }: Props) {
  const [form] = Form.useForm<FormValues>()
  const showOptions = question.type === 'single' || question.type === 'multiple'

  useEffect(() => {
    const answer = question.answer as unknown
    form.setFieldsValue({
      stem: question.stem,
      difficulty: question.difficulty,
      options: question.options ?? [],
      rubric: question.rubric ?? [],
      explanation: question.explanation ?? '',
      single: typeof answer === 'string' ? answer : undefined,
      multiple: Array.isArray(answer) ? (answer as string[]) : undefined,
      judge: typeof answer === 'boolean' ? answer : undefined,
      text: typeof answer === 'string' && !showOptions ? answer : undefined,
    })
  }, [question, form, showOptions])

  const buildAnswer = (values: FormValues): unknown => {
    switch (question.type) {
      case 'single':
        return values.single
      case 'multiple':
        return values.multiple ?? []
      case 'judge':
        return Boolean(values.judge)
      default:
        return values.text ?? ''
    }
  }

  return (
    <Form<FormValues>
      form={form}
      layout="vertical"
      onFinish={(values) =>
        onSubmit({
          stem: values.stem?.trim() ?? '',
          difficulty: values.difficulty ?? 3,
          options: showOptions ? (values.options ?? []).filter((o) => o?.key) : undefined,
          answer: buildAnswer(values),
          rubric: (values.rubric ?? []).filter((r) => r?.point),
          explanation: values.explanation,
        })
      }
    >
      <Space size={8} style={{ marginBottom: 12 }}>
        <Tag color="blue">{TYPE_LABEL[question.type] ?? question.type}</Tag>
        <Tag>难度 {question.difficulty}</Tag>
        {question.quality?.citation_ok ? <Tag color="green">溯源通过</Tag> : <Tag color="orange">待核验</Tag>}
      </Space>

      <Form.Item name="stem" label="题干" rules={[{ required: true, message: '题干不能为空' }]}>
        <Input.TextArea autoSize={{ minRows: 3, maxRows: 8 }} />
      </Form.Item>

      <Form.Item name="difficulty" label="难度（1-5）">
        <InputNumber min={1} max={5} style={{ width: 120 }} />
      </Form.Item>

      {showOptions && (
        <Form.List name="options">
          {(fields, { add, remove }) => (
            <Form.Item label="选项" required>
              <Space direction="vertical" style={{ width: '100%' }}>
                {fields.map((field) => (
                  <Space key={field.key} align="baseline" style={{ width: '100%' }}>
                    <Form.Item
                      name={[field.name, 'key']}
                      rules={[{ required: true, message: '选项标识' }]}
                      noStyle
                    >
                      <Input style={{ width: 64 }} placeholder="A" />
                    </Form.Item>
                    <Form.Item name={[field.name, 'text']} noStyle>
                      <Input style={{ width: 420 }} placeholder="选项内容" />
                    </Form.Item>
                    <Button type="text" danger icon={<DeleteOutlined />} onClick={() => remove(field.name)} />
                  </Space>
                ))}
                <Button type="dashed" icon={<PlusOutlined />} onClick={() => add({ key: '', text: '' })}>
                  添加选项
                </Button>
              </Space>
            </Form.Item>
          )}
        </Form.List>
      )}

      {question.type === 'single' && (
        <Form.Item name="single" label="正确答案" rules={[{ required: true, message: '请选择正确选项' }]}>
          <Select
            style={{ width: 200 }}
            options={(question.options ?? []).map((o) => ({ value: o.key, label: `${o.key}. ${o.text}` }))}
          />
        </Form.Item>
      )}
      {question.type === 'multiple' && (
        <Form.Item name="multiple" label="正确答案（多选）" rules={[{ required: true, message: '请选择正确选项' }]}>
          <Select
            mode="multiple"
            style={{ width: '100%' }}
            options={(question.options ?? []).map((o) => ({ value: o.key, label: `${o.key}. ${o.text}` }))}
          />
        </Form.Item>
      )}
      {question.type === 'judge' && (
        <Form.Item name="judge" label="正确答案" rules={[{ required: true, message: '请选择判断结果' }]}>
          <Select
            style={{ width: 200 }}
            options={[
              { value: true, label: '正确' },
              { value: false, label: '错误' },
            ]}
          />
        </Form.Item>
      )}
      {(question.type === 'short' || question.type === 'essay') && (
        <Form.Item name="text" label="参考答案">
          <Input.TextArea autoSize={{ minRows: 2, maxRows: 6 }} />
        </Form.Item>
      )}

      <Form.List name="rubric">
        {(fields, { add, remove }) => (
          <Form.Item label="评分要点（主观题按要点累计给分）">
            <Space direction="vertical" style={{ width: '100%' }}>
              {fields.map((field) => (
                <Space key={field.key} align="baseline">
                  <Form.Item name={[field.name, 'point']} noStyle>
                    <Input style={{ width: 420 }} placeholder="要点描述" />
                  </Form.Item>
                  <Form.Item name={[field.name, 'score']} noStyle>
                    <InputNumber min={0} step={0.5} style={{ width: 90 }} placeholder="分值" />
                  </Form.Item>
                  <Button type="text" danger icon={<DeleteOutlined />} onClick={() => remove(field.name)} />
                </Space>
              ))}
              <Button type="dashed" icon={<PlusOutlined />} onClick={() => add({ point: '', score: 1 })}>
                添加要点
              </Button>
            </Space>
          </Form.Item>
        )}
      </Form.List>

      <Form.Item name="explanation" label="解析">
        <Input.TextArea autoSize={{ minRows: 2, maxRows: 6 }} />
      </Form.Item>

      {question.source_refs?.length > 0 && (
        <Typography.Paragraph type="secondary" style={{ fontSize: 12 }}>
          溯源：{question.source_refs.map((r) => r.document_name).filter(Boolean).join('、') || '—'}
          {question.quality?.quote_match_ratio !== undefined &&
            `（引文匹配度 ${question.quality.quote_match_ratio.toFixed(2)}）`}
        </Typography.Paragraph>
      )}

      <Space>
        <Button type="primary" htmlType="submit" loading={saving}>
          保存
        </Button>
        {onCancel && <Button onClick={onCancel}>取消</Button>}
      </Space>
    </Form>
  )
}
