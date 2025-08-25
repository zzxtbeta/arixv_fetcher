import { Layout, Row, Col, theme, Menu } from 'antd'
import { useState } from 'react'
import OverviewCards from './components/OverviewCards'
import AuthorSearch from './components/AuthorSearch'
import LatestPapers from './components/LatestPapers'
import WebSearch from './components/WebSearch'
import OpenAlexSearch from './components/OpenAlexSearch'
import SessionManager from './components/SessionManager'

const { Header, Content, Footer } = Layout

export default function App() {
  const { token } = theme.useToken()
  const [activeTab, setActiveTab] = useState('dashboard')

  const menuItems = [
    {
      key: 'dashboard',
      label: '数据面板',
    },
    {
      key: 'sessions',
      label: '会话管理',
    },
  ]

  const renderContent = () => {
    switch (activeTab) {
      case 'sessions':
        return <SessionManager />
      case 'dashboard':
      default:
        return (
          <Row gutter={[16, 16]}>
            <Col xs={24}>
              <OverviewCards />
            </Col>
            <Col xs={24}>
              <OpenAlexSearch />
            </Col>
            <Col xs={24}>
              <AuthorSearch />
            </Col>
            <Col xs={24}>
              <WebSearch />
            </Col>
            <Col xs={24}>
              <LatestPapers />
            </Col>
          </Row>
        )
    }
  }

  return (
    <Layout style={{ minHeight: '100vh', background: `linear-gradient(180deg, ${token.colorBgLayout} 0%, #fdfdfd 100%)` }}>
      <Header style={{ background: 'transparent', padding: '16px 24px' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <div style={{ fontSize: 22, fontWeight: 700, letterSpacing: 0.3 }}>ArXiv Intelligence Dashboard</div>
          <Menu
            mode="horizontal"
            selectedKeys={[activeTab]}
            items={menuItems}
            onClick={({ key }) => setActiveTab(key)}
            style={{ background: 'transparent', border: 'none' }}
          />
        </div>
      </Header>
      <Content style={{ padding: 24 }}>
        {renderContent()}
      </Content>
      <Footer style={{ textAlign: 'center', background: 'transparent' }}>
        © {new Date().getFullYear()} ArXiv Scraper · Crafted with Ant Design
      </Footer>
    </Layout>
  )
}