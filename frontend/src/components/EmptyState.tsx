import { Empty } from 'antd'
import type { ReactNode } from 'react'

interface Props {
  description?: ReactNode
  action?: ReactNode
  image?: ReactNode
}

/** 统一空状态：所有列表页复用一个，避免各处文案风格不一 */
export default function EmptyState({ description = '暂无数据', action, image }: Props) {
  return (
    <div style={{ padding: '48px 0' }}>
      <Empty image={image ?? Empty.PRESENTED_IMAGE_SIMPLE} description={description}>
        {action}
      </Empty>
    </div>
  )
}
