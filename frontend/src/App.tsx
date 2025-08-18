import { Layout, Row, Col, theme } from 'antd'
import OverviewCards from './components/OverviewCards'
import AuthorSearch from './components/AuthorSearch'
import LatestPapers from './components/LatestPapers'
import WebSearch from './components/WebSearch'

const { Header, Content, Footer } = Layout

export default function App() {
  const { token } = theme.useToken()
  return (
    <Layout style={{ minHeight: '100vh', background: `linear-gradient(180deg, ${token.colorBgLayout} 0%, #fdfdfd 100%)` }}>
      <Header style={{ background: 'transparent', padding: '16px 24px' }}>
        <div style={{ fontSize: 22, fontWeight: 700, letterSpacing: 0.3 }}>ArXiv Intelligence Dashboard</div>
      </Header>
      <Content style={{ padding: 24 }}>
        <Row gutter={[16, 16]}>
          <Col xs={24}>
            <OverviewCards />
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
      </Content>
      <Footer style={{ textAlign: 'center', background: 'transparent' }}>
        © {new Date().getFullYear()} ArXiv Scraper · Crafted with Ant Design
      </Footer>
    </Layout>
  )
} 