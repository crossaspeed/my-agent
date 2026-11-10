import { Card, Col, Row, Skeleton } from 'antd'

interface Props {
  count?: number
  rows?: number
}

/** 列表页加载骨架，避免整页 Spin 造成布局跳动 */
export default function SkeletonCards({ count = 3, rows = 4 }: Props) {
  return (
    <Row gutter={[16, 16]}>
      {Array.from({ length: count }).map((_, index) => (
        <Col key={index} xs={24} md={12} xl={8}>
          <Card>
            <Skeleton active paragraph={{ rows }} title />
          </Card>
        </Col>
      ))}
    </Row>
  )
}
