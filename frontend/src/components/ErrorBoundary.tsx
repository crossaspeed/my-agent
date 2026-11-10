import { Component, type ErrorInfo, type ReactNode } from 'react'
import { Button, Result, Typography } from 'antd'

interface Props {
  children: ReactNode
}

interface State {
  error: Error | null
}

/** 页面级错误边界：单个页面崩溃不拖垮整个应用 */
export default class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null }

  static getDerivedStateFromError(error: Error): State {
    return { error }
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error('[ErrorBoundary]', error, info.componentStack)
  }

  render() {
    const { error } = this.state
    if (!error) return this.props.children
    return (
      <Result
        status="error"
        title="页面出错了"
        subTitle={
          <Typography.Text type="secondary" copyable>
            {error.message}
          </Typography.Text>
        }
        extra={
          <Button type="primary" onClick={() => this.setState({ error: null })}>
            重试
          </Button>
        }
      />
    )
  }
}
