import { Card, Input, List, Tag, Typography, Space, message, Button, Dropdown, MenuProps, Form, Row, Col, InputNumber, Collapse } from 'antd'
import { useState } from 'react'
import { searchAuthor } from '../api'
import { ArrowUpOutlined, ArrowDownOutlined, DownloadOutlined, SearchOutlined, ClearOutlined } from '@ant-design/icons'
import { CalendarOutlined } from '@ant-design/icons'

export default function AuthorSearch() {
  const [loading, setLoading] = useState(false)
  const [items, setItems] = useState<any[]>([])
  const [form] = Form.useForm()
  const [searchCriteria, setSearchCriteria] = useState<any>({})

  function parseRankValue(v?: string): number | null {
    if (!v) return null
    const m = String(v).match(/\d+/)
    return m ? Number(m[0]) : null
  }

  function formatDate(d?: string | null): string {
    if (!d) return ''
    const s = String(d)
    if (s.length >= 7) return s.slice(0, 7)
    if (s.length >= 4) return s.slice(0, 4)
    return s
  }

  function formatRange(start?: string | null, end?: string | null): string {
    const sd = formatDate(start) || '?'
    const ed = formatDate(end) || 'present'
    return `${sd} — ${ed}`
  }

  async function onSimpleSearch(v: string) {
    if (!v?.trim()) return
    setLoading(true)
    try {
      const data = await searchAuthor(v.trim())
      setItems(data.results || [])
      setSearchCriteria({ author_name: v.trim() })
    } catch (e: any) {
      message.error(e?.message || 'Search failed')
    } finally {
      setLoading(false)
    }
  }

  async function onAdvancedSearch(values: any) {
    // Remove empty values
    const cleanValues = Object.fromEntries(
      Object.entries(values).filter(([_, v]) => v !== undefined && v !== null && v !== '')
    )
    
    if (Object.keys(cleanValues).length === 0) {
      message.warning('请至少填写一个搜索条件')
      return
    }

    setLoading(true)
    try {
      const params = new URLSearchParams()
      Object.entries(cleanValues).forEach(([key, value]) => {
        if (value !== undefined && value !== null && value !== '') {
          params.append(key, String(value))
        }
      })
      
      const response = await fetch(`/dashboard/author/advanced?${params.toString()}`)
      const data = await response.json()
      
      if (response.ok) {
        setItems(data.results || [])
        setSearchCriteria(data.search_criteria || {})
        message.success(`找到 ${data.total || 0} 个结果`)
      } else {
        throw new Error(data.detail || '搜索失败')
      }
    } catch (e: any) {
      message.error(e?.message || 'Advanced search failed')
    } finally {
      setLoading(false)
    }
  }

  function onClearSearch() {
    form.resetFields()
    setItems([])
    setSearchCriteria({})
  }

  async function handleExportAuthors(format: 'json' | 'csv') {
    try {
      message.loading(`正在导出${format.toUpperCase()}数据...`, 0)
      
      if (format === 'csv') {
        // Handle CSV export with direct download
        const response = await fetch(`/dashboard/export-authors?format=csv`)
        
        if (response.ok) {
          const blob = await response.blob()
          const url = URL.createObjectURL(blob)
          
          const link = document.createElement('a')
          link.href = url
          link.download = `authors_export_${new Date().toISOString().split('T')[0]}.csv`
          document.body.appendChild(link)
          link.click()
          document.body.removeChild(link)
          URL.revokeObjectURL(url)
          
          message.destroy()
          message.success('成功导出CSV格式作者数据')
        } else {
          throw new Error('CSV导出失败')
        }
      } else {
        // Handle JSON export
        const response = await fetch('/dashboard/export-authors?format=json')
        const data = await response.json()
        
        if (response.ok && data.success) {
          // Create and download JSON file
          const jsonString = JSON.stringify(data.data, null, 2)
          const blob = new Blob([jsonString], { type: 'application/json' })
          const url = URL.createObjectURL(blob)
          
          const link = document.createElement('a')
          link.href = url
          link.download = `authors_export_${new Date().toISOString().split('T')[0]}.json`
          document.body.appendChild(link)
          link.click()
          document.body.removeChild(link)
          URL.revokeObjectURL(url)
          
          message.destroy()
          message.success(`成功导出 ${data.total_count} 条作者数据`)
        } else {
          throw new Error(data.detail || 'JSON导出失败')
        }
      }
    } catch (error: any) {
      console.error('Export error:', error)
      message.destroy()
      message.error('导出失败，请重试')
    }
  }

  return (
    <Card title="Author Search" extra={<Typography.Text type="secondary">支持多种搜索条件</Typography.Text>}>
      <Space direction="vertical" style={{ width: '100%' }} size="large">
        <Space style={{ width: '100%', justifyContent: 'flex-start' }}>
          <Dropdown
            menu={{
              items: [
                {
                  key: 'json',
                  label: '导出为JSON格式',
                  onClick: () => handleExportAuthors('json')
                },
                {
                  key: 'csv',
                  label: '导出为CSV格式',
                  onClick: () => handleExportAuthors('csv')
                }
              ] as MenuProps['items']
            }}
            placement="bottomLeft"
          >
            <Button type="primary" icon={<DownloadOutlined />}>
              导出作者数据
            </Button>
          </Dropdown>
        </Space>
        
        {/* Simple Search */}
        <Input.Search 
          placeholder="快速搜索作者姓名..." 
          enterButton="搜索" 
          loading={loading} 
          onSearch={onSimpleSearch} 
        />
        
        {/* Advanced Search */}
        <Collapse 
          items={[
            {
              key: 'advanced',
              label: '高级搜索',
              children: (
                <Form
                  form={form}
                  layout="vertical"
                  onFinish={onAdvancedSearch}
                >
                  <Row gutter={16}>
                    <Col xs={24} sm={12} md={8}>
                      <Form.Item name="author_name" label="作者姓名">
                        <Input placeholder="模糊搜索" />
                      </Form.Item>
                    </Col>
                    <Col xs={24} sm={12} md={8}>
                      <Form.Item name="email" label="邮箱">
                        <Input placeholder="模糊搜索" />
                      </Form.Item>
                    </Col>
                    <Col xs={24} sm={12} md={8}>
                      <Form.Item name="orcid" label="ORCID">
                        <Input placeholder="精确匹配" />
                      </Form.Item>
                    </Col>
                  </Row>
                  
                  <Row gutter={16}>
                    <Col xs={24} sm={12} md={8}>
                      <Form.Item name="paper_title" label="论文标题">
                        <Input placeholder="模糊搜索" />
                      </Form.Item>
                    </Col>
                    <Col xs={24} sm={12} md={8}>
                      <Form.Item name="affiliation_name" label="机构名称">
                        <Input placeholder="模糊搜索" />
                      </Form.Item>
                    </Col>
                    <Col xs={24} sm={12} md={8}>
                      <Form.Item name="role" label="职位/角色">
                        <Input placeholder="模糊搜索" />
                      </Form.Item>
                    </Col>
                  </Row>
                  
                  <Row gutter={16}>
                    <Col xs={24} sm={12} md={8}>
                      <Typography.Text strong>引用次数范围</Typography.Text>
                      <Input.Group compact style={{ marginTop: 8 }}>
                        <Form.Item name="citations_min" style={{ width: '50%', marginBottom: 0 }}>
                          <InputNumber placeholder="最小值" style={{ width: '100%' }} min={0} />
                        </Form.Item>
                        <Form.Item name="citations_max" style={{ width: '50%', marginBottom: 0 }}>
                          <InputNumber placeholder="最大值" style={{ width: '100%' }} min={0} />
                        </Form.Item>
                      </Input.Group>
                    </Col>
                    <Col xs={24} sm={12} md={8}>
                      <Typography.Text strong>H-Index范围</Typography.Text>
                      <Input.Group compact style={{ marginTop: 8 }}>
                        <Form.Item name="h_index_min" style={{ width: '50%', marginBottom: 0 }}>
                          <InputNumber placeholder="最小值" style={{ width: '100%' }} min={0} />
                        </Form.Item>
                        <Form.Item name="h_index_max" style={{ width: '50%', marginBottom: 0 }}>
                          <InputNumber placeholder="最大值" style={{ width: '100%' }} min={0} />
                        </Form.Item>
                      </Input.Group>
                    </Col>
                    <Col xs={24} sm={12} md={8}>
                      <Typography.Text strong>I10-Index范围</Typography.Text>
                      <Input.Group compact style={{ marginTop: 8 }}>
                        <Form.Item name="i10_index_min" style={{ width: '50%', marginBottom: 0 }}>
                          <InputNumber placeholder="最小值" style={{ width: '100%' }} min={0} />
                        </Form.Item>
                        <Form.Item name="i10_index_max" style={{ width: '50%', marginBottom: 0 }}>
                          <InputNumber placeholder="最大值" style={{ width: '100%' }} min={0} />
                        </Form.Item>
                      </Input.Group>
                    </Col>
                  </Row>
                  
                  <Row gutter={16} style={{ marginTop: 16 }}>
                    <Col>
                      <Space>
                        <Button type="primary" htmlType="submit" icon={<SearchOutlined />} loading={loading}>
                          高级搜索
                        </Button>
                        <Button icon={<ClearOutlined />} onClick={onClearSearch}>
                          清空条件
                        </Button>
                      </Space>
                    </Col>
                  </Row>
                </Form>
              )
            }
          ]}
        />
        
        {/* Search Results Summary */}
        {Object.keys(searchCriteria).length > 0 && (
          <Card size="small" style={{ backgroundColor: '#f6f8fa' }}>
            <Typography.Text type="secondary">
              <strong>搜索条件：</strong>
              {Object.entries(searchCriteria)
                .filter(([_, value]) => value !== null && value !== undefined && value !== '')
                .map(([key, value]) => {
                  const keyMap: Record<string, string> = {
                    author_name: '作者姓名',
                    email: '邮箱',
                    orcid: 'ORCID',
                    paper_title: '论文标题',
                    affiliation_name: '机构名称',
                    role: '职位角色',
                    citations_range: '引用次数',
                    h_index_range: 'H-Index',
                    i10_index_range: 'I10-Index'
                  }
                  const displayKey = keyMap[key] || key
                  const displayValue = Array.isArray(value) ? `${value[0] || 0}-${value[1] || '∞'}` : value
                  return `${displayKey}: ${displayValue}`
                })
                .join(' | ')}
            </Typography.Text>
          </Card>
        )}
        <List
          loading={loading}
          dataSource={items}
          renderItem={(it) => (
            <List.Item>
              <Space direction="vertical" style={{ width: '100%' }}>
                <Space align="center" wrap>
                  <Typography.Title level={5} style={{ margin: 0 }}>
                    {it.author?.name}
                    {it.author?.name_cn && it.author.name_cn !== 'Unknown' && (
                      <Typography.Text type="secondary" style={{ marginLeft: 8, fontSize: '14px' }}>
                        ({it.author.name_cn})
                      </Typography.Text>
                    )}
                  </Typography.Title>
                  {it.author?.orcid && it.author.orcid !== 'Unknown' ? (
                    <Tag color="success">
                      <a href={`https://orcid.org/${it.author.orcid}`} target="_blank" rel="noreferrer">
                        ORCID: {it.author.orcid}
                      </a>
                    </Tag>
                  ) : null}
                </Space>
                
                {/* Author Metrics */}
                <Space wrap>
                  {it.author?.citations > 0 && (
                    <Tag color="blue">引用: {it.author.citations}</Tag>
                  )}
                  {it.author?.h_index > 0 && (
                    <Tag color="green">H-Index: {it.author.h_index}</Tag>
                  )}
                  {it.author?.i10_index > 0 && (
                    <Tag color="orange">I10-Index: {it.author.i10_index}</Tag>
                  )}
                  {it.author?.email && it.author.email !== 'Unknown' && (
                    <Tag color="purple">{it.author.email}</Tag>
                  )}
                </Space>
                <Space wrap>
                  {(it.affiliations || []).map((a: any) => {
                    const y25n = parseRankValue(a?.qs?.y2025)
                    const y24n = parseRankValue(a?.qs?.y2024)
                    let arrow: any = null
                    if (y25n !== null && y24n !== null && y25n !== y24n) {
                      if (y25n < y24n) {
                        arrow = <ArrowUpOutlined style={{ color: '#cf1322' }} />
                      } else if (y25n > y24n) {
                        arrow = <ArrowDownOutlined style={{ color: '#52c41a' }} />
                      }
                    }
                    return (
                      <Card key={a.id} size="small" style={{ borderRadius: 8 }}>
                        <Space direction="vertical" size={4}>
                          <Typography.Text strong>{a.aff_name}</Typography.Text>
                          {/* line 1: role */}
                          {a.role ? (
                            <Space wrap size={6}>
                              <Tag color="magenta">{a.role}</Tag>
                            </Space>
                          ) : null}
                          {/* line 2: dates (range + latest) */}
                          {(a.start_date || a.end_date || a.latest_time) ? (
                            <Space wrap size={6}>
                              {(a.start_date || a.end_date) ? (
                                <Tag icon={<CalendarOutlined />}>{formatRange(a.start_date, a.end_date)}</Tag>
                              ) : null}
                              {a.latest_time ? <Tag>latest: {formatDate(a.latest_time)}</Tag> : null}
                            </Space>
                          ) : null}
                          {/* line 3: QS ranks with trend arrow placed before qs25 */}
                          {a?.qs?.y2025 || a?.qs?.y2024 ? (
                            <Space size={6} align="center">
                              {arrow}
                              <Tag color="geekblue">qs25: {a.qs?.y2025}</Tag>
                              <Tag>qs24: {a.qs?.y2024}</Tag>
                            </Space>
                          ) : null}
                        </Space>
                      </Card>
                    )
                  })}
                </Space>
                <Typography.Text strong>Recent papers ({(it.recent_papers || []).length})</Typography.Text>
                <ul style={{ paddingLeft: 18, margin: 0 }}>
                  {(it.recent_papers || []).slice(0, 5).map((p: any) => (
                    <li key={p.id}>
                      <a href={`https://arxiv.org/abs/${p.arxiv_entry}`} target="_blank" rel="noreferrer">{p.paper_title}</a>
                      {p.published ? <Typography.Text type="secondary"> — {formatDate(p.published)}</Typography.Text> : null}
                    </li>
                  ))}
                  {(it.recent_papers || []).length > 5 && (
                    <li>
                      <Typography.Text type="secondary">... 还有 {(it.recent_papers || []).length - 5} 篇论文</Typography.Text>
                    </li>
                  )}
                </ul>
                <Typography.Text strong>Top collaborators ({(it.top_collaborators || []).length})</Typography.Text>
                <Space wrap>
                  {(it.top_collaborators || []).slice(0, 8).map((c: any) => (
                    <Tag key={c.id} color="cyan">{c.name} ×{c.count}</Tag>
                  ))}
                  {(it.top_collaborators || []).length > 8 && (
                    <Typography.Text type="secondary">+{(it.top_collaborators || []).length - 8} more</Typography.Text>
                  )}
                </Space>
              </Space>
            </List.Item>
          )}
        />
      </Space>
    </Card>
  )
}