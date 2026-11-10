import { Card, Space, Tag, Tooltip, Typography } from 'antd'
import { FileTextOutlined, HighlightOutlined } from '@ant-design/icons'
import type { SourceRef } from '@/api/types'

interface Props {
  refItem: SourceRef
  index?: number
  compact?: boolean
}

/** 溯源卡片：展示模型引用的原文片段与文档定位（防幻觉的可信度可视化） */
export default function CitationCard({ refItem, index, compact }: Props) {
  const location = [
    refItem.document_name,
    refItem.page_no ? `第 ${refItem.page_no} 页` : null,
    refItem.slide_no ? `第 ${refItem.slide_no} 张` : null,
  ]
    .filter(Boolean)
    .join(' · ')

  const scoreColor = refItem.score >= 0.7 ? 'green' : refItem.score >= 0.4 ? 'blue' : 'default'

  return (
    <Card
      size="small"
      style={{ marginBottom: compact ? 8 : 12, background: 'rgba(22,119,255,0.03)' }}
      styles={{ body: { padding: compact ? 10 : 14 } }}
    >
      <Space direction="vertical" size={6} style={{ width: '100%' }}>
        <Space size={6} wrap>
          <Tag color="blue">
            <FileTextOutlined /> {index !== undefined ? `[${index + 1}]` : '引用'}
          </Tag>
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
            {location || `chunk #${refItem.chunk_id}`}
          </Typography.Text>
          <Tooltip title="混合检索相关性得分（向量 + BM25 RRF 融合）">
            <Tag color={scoreColor}>{refItem.score.toFixed(3)}</Tag>
          </Tooltip>
        </Space>
        {refItem.heading_path && (
          <Typography.Text style={{ fontSize: 12, color: '#1677ff' }}>
            <HighlightOutlined /> {refItem.heading_path}
          </Typography.Text>
        )}
        <Typography.Paragraph
          style={{ marginBottom: 0, fontSize: 13, color: '#595959' }}
          ellipsis={compact ? { rows: 3, expandable: true, symbol: '展开' } : false}
        >
          “{refItem.quote}”
        </Typography.Paragraph>
      </Space>
    </Card>
  )
}
