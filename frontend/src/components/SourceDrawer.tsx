import { Drawer, Empty, Space, Typography } from 'antd'
import CitationCard from './CitationCard'
import type { SourceRef } from '@/api/types'

interface Props {
  open: boolean
  refs: SourceRef[]
  onClose: () => void
  title?: string
}

/** 右侧溯源抽屉：题目/答疑引用的原文出处集中查看 */
export default function SourceDrawer({ open, refs, onClose, title = '溯源原文' }: Props) {
  return (
    <Drawer
      title={`${title}（${refs.length}）`}
      placement="right"
      width={520}
      open={open}
      onClose={onClose}
      destroyOnClose
    >
      {refs.length === 0 ? (
        <Empty description="暂无引用来源" />
      ) : (
        <Space direction="vertical" size={4} style={{ width: '100%' }}>
          <Typography.Paragraph type="secondary" style={{ fontSize: 12 }}>
            以下片段均来自本课程已解析的课件，服务端已校验 chunk_id 合法性并覆盖页码/文档名等元数据。
          </Typography.Paragraph>
          {refs.map((item, idx) => (
            <CitationCard key={`${item.chunk_id}-${idx}`} refItem={item} index={idx} />
          ))}
        </Space>
      )}
    </Drawer>
  )
}
