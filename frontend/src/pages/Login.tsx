import { LockOutlined, UserOutlined } from '@ant-design/icons'
import { Alert, App, Button, Card, Form, Input, Segmented, Space, Tabs, Typography } from 'antd'
import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { errorText } from '@/api/client'
import { useAuth } from '@/store/auth'

interface LoginForm {
  username: string
  password: string
}

interface RegisterForm {
  username: string
  password: string
  real_name?: string
  role: 'student' | 'teacher'
  invite_code?: string
}

export default function LoginPage() {
  const { message } = App.useApp()
  const login = useAuth((s) => s.login)
  const register = useAuth((s) => s.register)
  const navigate = useNavigate()
  const [loading, setLoading] = useState(false)
  const [role, setRole] = useState<'student' | 'teacher'>('student')

  const onLogin = async (values: LoginForm) => {
    setLoading(true)
    try {
      const user = await login(values.username.trim(), values.password)
      message.success(`欢迎回来，${user.real_name || user.username}`)
      navigate('/courses', { replace: true })
    } catch (error) {
      message.error(errorText(error))
    } finally {
      setLoading(false)
    }
  }

  const onRegister = async (values: RegisterForm) => {
    setLoading(true)
    try {
      await register({
        username: values.username.trim(),
        password: values.password,
        real_name: values.real_name,
        role: values.role,
        invite_code: values.role === 'teacher' ? values.invite_code : undefined,
      })
      message.success('注册成功，已自动登录')
      navigate('/courses', { replace: true })
    } catch (error) {
      message.error(errorText(error))
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="login-page">
      <div className="login-hero">
        <Typography.Title level={1} style={{ color: '#fff', marginBottom: 12 }}>
          智评导学
        </Typography.Title>
        <Typography.Paragraph style={{ color: 'rgba(255,255,255,0.88)', fontSize: 16, maxWidth: 460 }}>
          以课程课件为唯一事实来源，由出题官、阅卷官、导学师三个智能体协作完成
          「出题—审核—测评—阅卷—诊断—导学」闭环，每道题、每段讲解都可溯源到原文。
        </Typography.Paragraph>
        <Space direction="vertical" size={6} style={{ marginTop: 24 }}>
          {[
            '混合检索（向量 + BM25 + RRF）+ 引用校验，杜绝凭空出题',
            '主观题要点式评分 + 一致性复评，低置信自动转人工',
            '错题驱动导学，SSE 流式讲解并高亮原文出处',
          ].map((text) => (
            <Typography.Text key={text} style={{ color: 'rgba(255,255,255,0.82)' }}>
              · {text}
            </Typography.Text>
          ))}
        </Space>
      </div>

      <Card className="login-card" styles={{ body: { padding: 28 } }}>
        <Tabs
          items={[
            {
              key: 'login',
              label: '登录',
              children: (
                <Form<LoginForm> layout="vertical" onFinish={onLogin} requiredMark={false}>
                  <Form.Item name="username" label="用户名" rules={[{ required: true, message: '请输入用户名' }]}>
                    <Input size="large" prefix={<UserOutlined />} placeholder="teacher / student" autoComplete="username" />
                  </Form.Item>
                  <Form.Item name="password" label="密码" rules={[{ required: true, message: '请输入密码' }]}>
                    <Input.Password size="large" prefix={<LockOutlined />} placeholder="123456" autoComplete="current-password" />
                  </Form.Item>
                  <Button type="primary" size="large" htmlType="submit" block loading={loading}>
                    登录
                  </Button>
                  <Alert
                    style={{ marginTop: 16 }}
                    type="info"
                    showIcon
                    message="演示账号"
                    description="teacher / student（密码 123456），由 make seed 生成"
                  />
                </Form>
              ),
            },
            {
              key: 'register',
              label: '注册',
              children: (
                <Form<RegisterForm>
                  layout="vertical"
                  onFinish={onRegister}
                  requiredMark={false}
                  initialValues={{ role: 'student' }}
                  onValuesChange={(changed) => {
                    if (changed.role) setRole(changed.role as 'student' | 'teacher')
                  }}
                >
                  <Form.Item name="username" label="用户名" rules={[{ required: true, min: 3, message: '至少 3 个字符' }]}>
                    <Input size="large" prefix={<UserOutlined />} placeholder="登录用户名" />
                  </Form.Item>
                  <Form.Item name="password" label="密码" rules={[{ required: true, min: 6, message: '至少 6 位' }]}>
                    <Input.Password size="large" prefix={<LockOutlined />} placeholder="至少 6 位" />
                  </Form.Item>
                  <Form.Item name="real_name" label="姓名">
                    <Input size="large" placeholder="选填" />
                  </Form.Item>
                  <Form.Item name="role" label="身份">
                    <Segmented
                      options={[
                        { label: '学生', value: 'student' },
                        { label: '教师', value: 'teacher' },
                      ]}
                    />
                  </Form.Item>
                  {role === 'teacher' && (
                    <Form.Item
                      name="invite_code"
                      label="教师邀请码"
                      rules={[{ required: true, message: '教师注册需要邀请码' }]}
                      extra="默认 TEACHER2026（由后端 env 配置，生产环境务必修改）"
                    >
                      <Input size="large" placeholder="邀请码" />
                    </Form.Item>
                  )}
                  <Button type="primary" size="large" htmlType="submit" block loading={loading}>
                    注册并登录
                  </Button>
                </Form>
              ),
            },
          ]}
        />
      </Card>
    </div>
  )
}
