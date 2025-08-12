import { Card, Col, Row, Statistic, Skeleton, message } from 'antd'
import { useEffect, useState } from 'react'
import { getOverview } from '../api'

export default function OverviewCards() {
  const [loading, setLoading] = useState(true)
  const [data, setData] = useState<{ papers: number; authors: number; affiliations: number; categories: number } | null>(null)

  useEffect(() => {
    ;(async () => {
      try {
        const d = await getOverview()
        setData(d)
      } catch (e: any) {
        message.error(e?.message || 'Failed to load overview')
      } finally {
        setLoading(false)
      }
    })()
  }, [])

  if (loading) return <Skeleton active paragraph={false} />
  if (!data) return null

  return (
    <Row gutter={16}>
      <Col span={6}><Card><Statistic title="Papers" value={data.papers} /></Card></Col>
      <Col span={6}><Card><Statistic title="Authors" value={data.authors} /></Card></Col>
      <Col span={6}><Card><Statistic title="Affiliations" value={data.affiliations} /></Card></Col>
      <Col span={6}><Card><Statistic title="Categories" value={data.categories} /></Card></Col>
    </Row>
  )
} 