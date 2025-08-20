import React, { useState, useCallback } from 'react';
import { 
  Card, 
  Tabs, 
  Form, 
  Input, 
  Select, 
  Button, 
  Table, 
  Tag, 
  Space, 
  Statistic, 
  Row, 
  Col,
  message,
  Collapse,
  Typography,
  Tooltip,
  Badge,
  Divider,
  AutoComplete,
  Alert,
  Spin
} from 'antd';
import { 
  SearchOutlined, 
  UserOutlined, 
  BookOutlined, 
  BankOutlined,
  TrophyOutlined,
  TeamOutlined,
  LineChartOutlined,
  ExperimentOutlined,
  InfoCircleOutlined,
  BulbOutlined
} from '@ant-design/icons';
import type { ColumnsType } from 'antd/es/table';
import {
  searchOpenAlexAuthors,
  findPhdCandidates,
  getAuthorCollaboration,
  searchOpenAlexPapers,
  searchOpenAlexInstitutions,
  getInstitutionProfile,
  type OpenAlexAuthor,
  type OpenAlexPaper,
  type OpenAlexInstitution
} from '../api';

const { TabPane } = Tabs;
const { Option } = Select;
const { TextArea } = Input;
const { Text, Title, Paragraph } = Typography;
const { Panel } = Collapse;

// 使用导入的类型别名
type Author = OpenAlexAuthor;
type Paper = OpenAlexPaper;
type Institution = OpenAlexInstitution;

const OpenAlexSearch: React.FC = () => {
  const [loading, setLoading] = useState(false);
  const [authorResults, setAuthorResults] = useState<Author[]>([]);
  const [paperResults, setPaperResults] = useState<Paper[]>([]);
  const [institutionResults, setInstitutionResults] = useState<Institution[]>([]);
  const [phdCandidates, setPhdCandidates] = useState<Author[]>([]);
  const [institutionProfile, setInstitutionProfile] = useState<any>(null);
  const [collaborationNetwork, setCollaborationNetwork] = useState<any>(null);
  const [showTips, setShowTips] = useState(false);
  const [activeTab, setActiveTab] = useState('authors');

  // 输入清理函数
  const cleanInput = useCallback((value: string) => {
    if (!value) return '';
    return value
      .replace(/[_.]/g, ' ')        // 将下划线和点替换为空格
      .replace(/\s+/g, ' ')         // 合并多个空格
      .trim();                      // 去除首尾空格
  }, []);

  // Predefined options for better UX
  const institutionOptions = [
    'Stanford University', 'MIT', 'Harvard University', 'Carnegie Mellon University',
    'University of California Berkeley', 'Princeton University', 'Yale University',
    'University of Oxford', 'University of Cambridge', 'Imperial College London',
    'ETH Zurich', 'Technical University of Munich', 'University of Toronto',
    'Tsinghua University', 'Peking University', 'Shanghai Jiao Tong University'
  ];

  const researchAreaOptions = [
    'artificial intelligence', 'machine learning', 'deep learning', 'computer vision',
    'natural language processing', 'robotics', 'data mining', 'computer science',
    'software engineering', 'cybersecurity', 'human-computer interaction',
    'distributed systems', 'algorithms', 'database systems', 'neural networks'
  ];

  const countryOptions = [
    { label: '�� United States', value: 'US' },
    { label: '�� China', value: 'CN' },
    { label: '🇬🇧 United Kingdom', value: 'GB' },
    { label: '�� Germany', value: 'DE' },
    { label: '�� France', value: 'FR' },
    { label: '�� Japan', value: 'JP' },
    { label: '🇨🇦 Canada', value: 'CA' },
    { label: '🇦🇺 Australia', value: 'AU' }
  ];

  // Smart search suggestions
  const getSearchSuggestions = useCallback((category: string, value: string) => {
    const cleanValue = cleanInput(value).toLowerCase();
    if (!cleanValue || cleanValue.length < 2) return [];
    
    switch (category) {
      case 'institution':
        return institutionOptions.filter(opt => 
          opt.toLowerCase().includes(cleanValue)
        ).map(opt => ({ value: opt, label: opt }));
      case 'research':
        return researchAreaOptions.filter(opt => 
          opt.toLowerCase().includes(cleanValue)
        ).map(opt => ({ value: opt, label: opt }));
      default:
        return [];
    }
  }, [cleanInput]);

  // Enhanced search tips component
  const SearchTips: React.FC = () => (
    <Alert
      message="🎯 Smart Search Tips"
      description={
        <div style={{ fontSize: '12px' }}>
          <div>• <strong>Case Insensitive</strong>: andrew ng = Andrew Ng = ANDREW NG</div>
          <div>• <strong>Smart Spacing</strong>: machine learning = machine-learning ≠ machinelearning</div>
          <div>• <strong>Institution Names</strong>: Use full names (Stanford University &gt; Stanford Univ)</div>
          <div>• <strong>Multiple Values</strong>: Separate with commas, English names work best</div>
          <div>• <strong>Auto Clean</strong>: System automatically optimizes your input format</div>
        </div>
      }
      type="info"
      showIcon
      closable
      style={{ marginBottom: 16 }}
    />
  );

  // 搜索作者
  const searchAuthors = async (values: any) => {
    setLoading(true);
    try {
      const params = {
        name: values.author_name,
        institutions: values.institutions,
        country: values.country,
        per_page: 50
      };

      const data = await searchOpenAlexAuthors(params);
      
      if (data.success) {
        setAuthorResults(data.authors);
        if (data.count > 0) {
          message.success(`找到 ${data.count} 位作者，显示前 ${data.authors.length} 位`);
        } else {
          message.info('未找到匹配的作者，建议：使用作者全名或调整搜索条件');
        }
      } else {
        message.error(data.message || '搜索失败，请检查网络连接或稍后重试');
      }
    } catch (error) {
      message.error('搜索出错，请检查输入格式或稍后重试');
      console.error('Author search error:', error);
    } finally {
      setLoading(false);
    }
  };

  // 查找博士生候选人
  const findPhdCandidatesHandler = async (values: any) => {
    setLoading(true);
    try {
      const params = {
        institutions: values.phd_institutions,
        research_areas: values.research_areas,
        country: values.country,
        min_works: values.min_works,
        max_works: values.max_works,
        recent_years: 5
      };

      const data = await findPhdCandidates(params);
      
      if (data.success) {
        setPhdCandidates(data.candidates);
        if (data.count > 0) {
          message.success(`找到 ${data.count} 位疑似博士生，基于论文数量和机构关联分析`);
        } else {
          message.info('未找到符合条件的博士生候选人，建议：检查机构名称或调整筛选条件');
        }
      } else {
        message.error(data.message || '搜索失败，请检查机构名称或稍后重试');
      }
    } catch (error) {
      message.error('搜索出错，请检查机构名称格式或稍后重试');
      console.error('PhD search error:', error);
    } finally {
      setLoading(false);
    }
  };

  // 搜索论文
  const searchPapers = async (values: any) => {
    setLoading(true);
    try {
      const params = {
        title: values.paper_title,
        author_name: values.paper_author,
        institutions: values.paper_institutions,
        concepts: values.concepts,
        publication_year_start: values.year_start,
        publication_year_end: values.year_end,
        is_oa: values.is_oa,
        min_citations: values.min_citations,
        sort_by: values.sort_by || 'cited_by_count',
        per_page: 50
      };

      const data = await searchOpenAlexPapers(params);
      
      if (data.success) {
        setPaperResults(data.papers);
        if (data.count > 0) {
          message.success(`找到 ${data.count} 篇论文，按${values.sort_by === 'cited_by_count' ? '引用数' : '发表时间'}排序`);
        } else {
          message.info('未找到匹配的论文，建议：使用更通用的关键词或调整筛选条件');
        }
      } else {
        message.error(data.message || '搜索失败，请检查搜索条件或稍后重试');
      }
    } catch (error) {
      message.error('搜索出错，请检查输入格式或稍后重试');
      console.error('Paper search error:', error);
    } finally {
      setLoading(false);
    }
  };

  // 搜索机构
  const searchInstitutions = async (values: any) => {
    setLoading(true);
    try {
      const params = {
        query: values.institution_query,
        country: values.inst_country,
        institution_type: values.inst_type,
        per_page: 50
      };

      const data = await searchOpenAlexInstitutions(params);
      
      if (data.success) {
        setInstitutionResults(data.institutions);
        message.success(`找到 ${data.count} 个机构`);
      } else {
        message.error('搜索失败');
      }
    } catch (error) {
      message.error('搜索出错');
    } finally {
      setLoading(false);
    }
  };

  // 获取机构概况
  const getInstitutionProfileHandler = async (name: string) => {
    setLoading(true);
    try {
      const params = {
        name: name,
        years_back: 5
      };

      const data = await getInstitutionProfile(params);
      
      if (data.success) {
        setInstitutionProfile(data.institution_profile);
        message.success('机构概况获取成功');
      } else {
        message.error('获取失败');
      }
    } catch (error) {
      message.error('获取出错');
    } finally {
      setLoading(false);
    }
  };

  // 获取合作网络
  const getCollaborationNetworkHandler = async (authorId: string) => {
    setLoading(true);
    try {
      const data = await getAuthorCollaboration(authorId, 20);
      
      if (data.success) {
        setCollaborationNetwork(data.collaboration_network);
        message.success('Collaboration network retrieved successfully');
      } else {
        message.error('获取失败');
      }
    } catch (error) {
      message.error('获取出错');
    } finally {
      setLoading(false);
    }
  };

  // 作者表格列定义
  const authorColumns: ColumnsType<Author> = [
    {
      title: '作者姓名',
      dataIndex: 'display_name',
      key: 'name',
      render: (name: string, record: Author) => (
        <Space direction="vertical" size={0}>
          <Text strong>{name}</Text>
          {record.orcid && (
            <Text type="secondary" style={{ fontSize: '12px' }}>
              ORCID: {record.orcid.split('/').pop()}
            </Text>
          )}
        </Space>
      ),
    },
    {
      title: '当前机构',
      dataIndex: 'current_institution',
      key: 'institution',
      render: (inst: Author['current_institution']) => (
        inst ? (
          <Space direction="vertical" size={0}>
            <Text>{inst.name}</Text>
            <Tag color="blue">{inst.country}</Tag>
          </Space>
        ) : '-'
      ),
    },
    {
      title: '学术指标',
      key: 'metrics',
      render: (_, record: Author) => (
        <Space direction="vertical" size={0}>
          <Text>论文: {record.works_count}</Text>
          <Text>引用: {record.cited_by_count}</Text>
          <Text>H指数: {record.h_index}</Text>
          {record.academic_age && <Text>学龄: {record.academic_age}年</Text>}
        </Space>
      ),
    },
    {
      title: '研究领域',
      dataIndex: 'research_areas',
      key: 'areas',
      render: (areas: Author['research_areas']) => (
        <Space wrap>
          {areas?.slice(0, 3).map((area, index) => (
            <Tag key={index} color="green">
              {area.name}
            </Tag>
          ))}
        </Space>
      ),
    },
    {
      title: '操作',
      key: 'actions',
      render: (_, record: Author) => (
        <Space>
          <Button 
            size="small" 
            onClick={() => getCollaborationNetworkHandler(record.id)}
          >
            Collaboration Network
          </Button>
        </Space>
      ),
    },
  ];

  // 博士生候选人列定义
  const phdColumns: ColumnsType<Author> = [
    ...authorColumns,
    {
      title: '可能性得分',
      dataIndex: 'phd_likelihood_score',
      key: 'score',
      render: (score: number) => (
        <Badge
          count={`${(score * 100).toFixed(0)}%`}
          style={{ backgroundColor: score > 0.7 ? '#52c41a' : score > 0.5 ? '#faad14' : '#f5222d' }}
        />
      ),
      sorter: (a: Author, b: Author) => (a.phd_likelihood_score || 0) - (b.phd_likelihood_score || 0),
    },
  ];

  // 论文表格列定义
  const paperColumns: ColumnsType<Paper> = [
    {
      title: '论文标题',
      dataIndex: 'title',
      key: 'title',
      render: (title: string, record: Paper) => (
        <Space direction="vertical" size={0}>
          <Text strong style={{ fontSize: '14px' }}>{title}</Text>
          <Space>
            <Tag color="blue">{record.publication_year}</Tag>
            {record.is_oa && <Tag color="green">开放获取</Tag>}
            <Text type="secondary">引用: {record.cited_by_count}</Text>
            {record.trending_score && (
              <Tag color="red">趋势: {(record.trending_score * 100).toFixed(0)}%</Tag>
            )}
          </Space>
        </Space>
      ),
    },
    {
      title: '作者',
      dataIndex: 'authors',
      key: 'authors',
      render: (authors: Paper['authors']) => (
        <Space direction="vertical" size={0}>
          {authors.slice(0, 3).map((author, index) => (
            <Text key={index} style={{ fontSize: '12px' }}>
              {author.name} {author.is_corresponding && <Tag color="orange">通讯</Tag>}
            </Text>
          ))}
          {authors.length > 3 && <Text type="secondary">等 {authors.length} 人</Text>}
        </Space>
      ),
    },
    {
      title: '机构',
      dataIndex: 'institutions',
      key: 'institutions',
      render: (institutions: string[]) => (
        <Space wrap>
          {institutions.slice(0, 2).map((inst, index) => (
            <Tag key={index} style={{ fontSize: '11px' }}>
              {inst}
            </Tag>
          ))}
        </Space>
      ),
    },
  ];

  // 机构表格列定义
  const institutionColumns: ColumnsType<Institution> = [
    {
      title: '机构名称',
      dataIndex: 'display_name',
      key: 'name',
      render: (name: string, record: Institution) => (
        <Space direction="vertical" size={0}>
          <Text strong>{name}</Text>
          <Space>
            <Tag color="blue">{record.country_code}</Tag>
            <Tag>{record.type}</Tag>
          </Space>
        </Space>
      ),
    },
    {
      title: '学术指标',
      key: 'metrics',
      render: (_, record: Institution) => (
        <Space direction="vertical" size={0}>
          <Text>论文: {record.works_count?.toLocaleString()}</Text>
          <Text>引用: {record.cited_by_count?.toLocaleString()}</Text>
        </Space>
      ),
    },
    {
      title: '操作',
      key: 'actions',
      render: (_, record: Institution) => (
        <Space>
          <Button 
            size="small" 
            onClick={() => getInstitutionProfileHandler(record.display_name)}
          >
            查看概况
          </Button>
          {record.homepage_url && (
            <Button 
              size="small" 
              type="link"
              href={record.homepage_url}
              target="_blank"
            >
              官网
            </Button>
          )}
        </Space>
      ),
    },
  ];

  return (
    <Card title={
      <Space>
        <ExperimentOutlined />
        <Title level={4} style={{ margin: 0 }}>OpenAlex Global Academic Search System</Title>
        <Tooltip title="Click to view search tips">
          <Button 
            type="text" 
            size="small" 
            icon={<InfoCircleOutlined />}
            onClick={() => setShowTips(!showTips)}
          />
        </Tooltip>
      </Space>
    }>
      {showTips && <SearchTips />}
      
      <Tabs 
        defaultActiveKey="authors" 
        type="card"
        onChange={setActiveTab}
      >
        <TabPane 
          tab={<Space><UserOutlined />Author Search</Space>} 
          key="authors"
        >
          <Space direction="vertical" size="large" style={{ width: '100%' }}>
            <Card title="🔍 Smart Author Search" size="small" style={{ borderRadius: '8px' }}>
              <Form onFinish={searchAuthors} layout="vertical">
                <Row gutter={16}>
                  <Col span={8}>
                    <Form.Item name="author_name" label="Author Name">
                      <Input 
                        placeholder="e.g., Andrew Ng, Yann LeCun" 
                        prefix={<UserOutlined style={{ color: '#1890ff' }} />}
                      />
                    </Form.Item>
                  </Col>
                  <Col span={8}>
                    <Form.Item name="institutions" label="Affiliated Institutions">
                      <AutoComplete
                        placeholder="e.g., Stanford University, MIT"
                        options={institutionOptions.map(opt => ({ value: opt, label: opt }))}
                        filterOption={(inputValue, option) =>
                          option?.label?.toLowerCase().includes(inputValue.toLowerCase()) || false
                        }
                      />
                    </Form.Item>
                  </Col>
                  <Col span={6}>
                    <Form.Item name="country" label="Country/Region">
                      <Select placeholder="Select Country">
                        {countryOptions.map(option => (
                          <Option key={option.value} value={option.value}>
                            {option.label}
                          </Option>
                        ))}
                      </Select>
                    </Form.Item>
                  </Col>
                  <Col span={2}>
                    <Form.Item label=" ">
                      <Button 
                        type="primary" 
                        htmlType="submit" 
                        loading={loading}
                        block
                        style={{ borderRadius: '6px' }}
                      >
                        <SearchOutlined /> Search
                      </Button>
                    </Form.Item>
                  </Col>
                </Row>
              </Form>
            </Card>

            {authorResults.length > 0 && (
              <Card 
                title={
                  <Space>
                    <Badge count={authorResults.length} style={{ backgroundColor: '#52c41a' }} />
                    <Text strong>Search Results</Text>
                  </Space>
                }
                extra={
                  <Button 
                    size="small" 
                    onClick={() => setAuthorResults([])}
                    type="text"
                  >
                    Clear Results
                  </Button>
                }
              >
                <Table
                  dataSource={authorResults}
                  columns={authorColumns}
                  rowKey="id"
                  pagination={{ pageSize: 10, showSizeChanger: true, showQuickJumper: true }}
                  size="small"
                  style={{ borderRadius: '8px' }}
                />
              </Card>
            )}
          </Space>
        </TabPane>

        <TabPane 
          tab={<Space><TrophyOutlined />PhD Candidates</Space>} 
          key="phd"
        >
          <Space direction="vertical" size="large" style={{ width: '100%' }}>
            <Card title="🎓 PhD Candidate Intelligence Detection" size="small" style={{ borderRadius: '8px' }}>
              <Alert
                message="💡 Recommended Working Examples"
                description={
                  <Space wrap>
                    <Button size="small" type="link" 
                      onClick={() => {
                        const form = document.getElementById('phd-form');
                        const instInput = form?.querySelector('[name="phd_institutions"]') as HTMLInputElement;
                        const areaInput = form?.querySelector('[name="research_areas"]') as HTMLInputElement;
                        if (instInput) instInput.value = 'MIT';
                        if (areaInput) areaInput.value = 'computer science';
                      }}>
                      MIT + CS
                    </Button>
                    <Button size="small" type="link"
                      onClick={() => {
                        const form = document.getElementById('phd-form');
                        const instInput = form?.querySelector('[name="phd_institutions"]') as HTMLInputElement;
                        const areaInput = form?.querySelector('[name="research_areas"]') as HTMLInputElement;
                        if (instInput) instInput.value = 'Stanford University';
                        if (areaInput) areaInput.value = 'artificial intelligence';
                      }}>
                      Stanford + AI
                    </Button>
                    <Button size="small" type="link"
                      onClick={() => {
                        const form = document.getElementById('phd-form');
                        const instInput = form?.querySelector('[name="phd_institutions"]') as HTMLInputElement;
                        const areaInput = form?.querySelector('[name="research_areas"]') as HTMLInputElement;
                        if (instInput) instInput.value = 'Carnegie Mellon University';
                        if (areaInput) areaInput.value = 'machine learning';
                      }}>
                      CMU + ML
                    </Button>
                    <Button size="small" type="link"
                      onClick={() => {
                        const form = document.getElementById('phd-form');
                        const instInput = form?.querySelector('[name="phd_institutions"]') as HTMLInputElement;
                        const areaInput = form?.querySelector('[name="research_areas"]') as HTMLInputElement;
                        if (instInput) instInput.value = 'Tsinghua University';
                        if (areaInput) areaInput.value = 'artificial intelligence';
                      }}>
                      Tsinghua + AI
                    </Button>
                  </Space>
                }
                type="info"
                showIcon
                style={{ marginBottom: 16 }}
              />
              
              <Form id="phd-form" onFinish={findPhdCandidatesHandler} layout="vertical">
                <Row gutter={16}>
                  <Col span={12}>
                    <Form.Item 
                      name="phd_institutions" 
                      label="🏫 Target Institutions" 
                      rules={[{ required: true, message: 'Please enter target institutions' }]}
                    >
                      <AutoComplete
                        placeholder="e.g., MIT, Stanford University, Tsinghua University"
                        options={institutionOptions.map(opt => ({ value: opt, label: opt }))}
                        filterOption={(inputValue, option) =>
                          option?.label?.toLowerCase().includes(inputValue.toLowerCase()) || false
                        }
                      />
                    </Form.Item>
                  </Col>
                  <Col span={12}>
                    <Form.Item name="research_areas" label="🔬 Research Areas">
                      <AutoComplete
                        placeholder="e.g., machine learning, computer science"
                        defaultValue="computer science,artificial intelligence"
                        options={researchAreaOptions.map(opt => ({ value: opt, label: opt }))}
                        filterOption={(inputValue, option) =>
                          option?.label?.toLowerCase().includes(inputValue.toLowerCase()) || false
                        }
                      />
                    </Form.Item>
                  </Col>
                </Row>
                <Row gutter={16}>
                  <Col span={6}>
                    <Form.Item name="country" label="🌍 Country" initialValue="US">
                      <Select>
                        {countryOptions.map(option => (
                          <Option key={option.value} value={option.value}>
                            {option.label}
                          </Option>
                        ))}
                      </Select>
                    </Form.Item>
                  </Col>
                  <Col span={4}>
                    <Form.Item name="min_works" label="Min Papers" initialValue={1}>
                      <Input type="number" min={1} max={10} />
                    </Form.Item>
                  </Col>
                  <Col span={4}>
                    <Form.Item name="max_works" label="Max Papers" initialValue={25}>
                      <Input type="number" min={10} max={50} />
                    </Form.Item>
                  </Col>
                  <Col span={4}>
                    <Form.Item name="recent_years" label="Time Window" initialValue={8}>
                      <Select>
                        <Option value={5}>5 Years</Option>
                        <Option value={8}>8 Years</Option>
                        <Option value={10}>10 Years</Option>
                      </Select>
                    </Form.Item>
                  </Col>
                  <Col span={6}>
                    <Form.Item label=" ">
                      <Button type="primary" htmlType="submit" loading={loading} block>
                        <SearchOutlined /> Find PhD Students
                      </Button>
                    </Form.Item>
                  </Col>
                </Row>
              </Form>
            </Card>

            {phdCandidates.length > 0 && (
              <Card title={
                <Space>
                  <Badge count={phdCandidates.length} style={{ backgroundColor: '#faad14' }} />
                  <Text strong>Potential PhD Candidates</Text>
                  <Tag color="orange">Based on Heuristic Rules</Tag>
                </Space>
              }>
                <Table
                  dataSource={phdCandidates}
                  columns={phdColumns}
                  rowKey="id"
                  pagination={{ pageSize: 10, showSizeChanger: true }}
                  size="small"
                />
              </Card>
            )}
          </Space>
        </TabPane>

        <TabPane 
          tab={<Space><BookOutlined />Paper Search</Space>} 
          key="papers"
        >
          <Space direction="vertical" size="large" style={{ width: '100%' }}>
            <Card title="📚 Advanced Paper Search" size="small" style={{ borderRadius: '8px' }}>
              <Form onFinish={searchPapers} layout="vertical">
                <Row gutter={16}>
                  <Col span={12}>
                    <Form.Item name="paper_title" label="📄 Paper Title">
                      <Input 
                        placeholder="e.g., transformer, attention mechanism"
                        prefix={<BookOutlined style={{ color: '#1890ff' }} />}
                      />
                    </Form.Item>
                  </Col>
                  <Col span={12}>
                    <Form.Item name="paper_author" label="👤 Author Name">
                      <Input 
                        placeholder="e.g., Yann LeCun, Ashish Vaswani"
                        prefix={<UserOutlined style={{ color: '#1890ff' }} />}
                      />
                    </Form.Item>
                  </Col>
                </Row>
                <Row gutter={16}>
                  <Col span={12}>
                    <Form.Item name="paper_institutions" label="🏫 Institutions">
                      <AutoComplete
                        placeholder="e.g., MIT, Stanford University"
                        options={institutionOptions.map(opt => ({ value: opt, label: opt }))}
                        filterOption={(inputValue, option) =>
                          option?.label?.toLowerCase().includes(inputValue.toLowerCase()) || false
                        }
                      />
                    </Form.Item>
                  </Col>
                  <Col span={12}>
                    <Form.Item name="concepts" label="🔬 Research Areas">
                      <AutoComplete
                        placeholder="e.g., computer vision, natural language processing"
                        options={researchAreaOptions.map(opt => ({ value: opt, label: opt }))}
                        filterOption={(inputValue, option) =>
                          option?.label?.toLowerCase().includes(inputValue.toLowerCase()) || false
                        }
                      />
                    </Form.Item>
                  </Col>
                </Row>
                <Row gutter={16}>
                  <Col span={5}>
                    <Form.Item name="year_start" label="Start Year">
                      <Select placeholder="Start Year">
                        {Array.from({length: 25}, (_, i) => 2024 - i).map(year => (
                          <Option key={year} value={year}>{year}</Option>
                        ))}
                      </Select>
                    </Form.Item>
                  </Col>
                  <Col span={5}>
                    <Form.Item name="year_end" label="End Year">
                      <Select placeholder="End Year">
                        {Array.from({length: 25}, (_, i) => 2024 - i).map(year => (
                          <Option key={year} value={year}>{year}</Option>
                        ))}
                      </Select>
                    </Form.Item>
                  </Col>
                  <Col span={4}>
                    <Form.Item name="min_citations" label="Min Citations">
                      <Input type="number" placeholder="e.g., 10" min={0} />
                    </Form.Item>
                  </Col>
                  <Col span={4}>
                    <Form.Item name="is_oa" label="Open Access">
                      <Select placeholder="Select">
                        <Option value={true}>✅ Yes</Option>
                        <Option value={false}>❌ No</Option>
                      </Select>
                    </Form.Item>
                  </Col>
                  <Col span={4}>
                    <Form.Item name="sort_by" label="Sort By" initialValue="cited_by_count">
                      <Select>
                        <Option value="cited_by_count">📊 Citations</Option>
                        <Option value="publication_date">📅 Date</Option>
                        <Option value="relevance_score">🎯 Relevance</Option>
                      </Select>
                    </Form.Item>
                  </Col>
                  <Col span={2}>
                    <Form.Item label=" ">
                      <Button type="primary" htmlType="submit" loading={loading} block>
                        <SearchOutlined />
                      </Button>
                    </Form.Item>
                  </Col>
                </Row>
              </Form>
            </Card>

            {paperResults.length > 0 && (
              <Card title={
                <Space>
                  <Badge count={paperResults.length} style={{ backgroundColor: '#722ed1' }} />
                  <Text strong>Paper Search Results</Text>
                </Space>
              }>
                <Table
                  dataSource={paperResults}
                  columns={paperColumns}
                  rowKey="id"
                  pagination={{ pageSize: 8, showSizeChanger: true, showQuickJumper: true }}
                  size="small"
                  expandable={{
                    expandedRowRender: (record: Paper) => (
                      record.abstract && (
                        <div style={{ padding: '12px', backgroundColor: '#fafafa', borderRadius: '6px' }}>
                          <Text strong style={{ color: '#1890ff' }}>Abstract:</Text>
                          <br />
                          <Paragraph style={{ marginTop: 8, marginBottom: 0 }}>
                            {record.abstract.substring(0, 800)}
                            {record.abstract.length > 800 && '...'}
                          </Paragraph>
                        </div>
                      )
                    ),
                    rowExpandable: (record: Paper) => !!record.abstract,
                  }}
                />
              </Card>
            )}
          </Space>
        </TabPane>

        <TabPane 
          tab={<Space><BankOutlined />Institution Analysis</Space>} 
          key="institutions"
        >
          <Space direction="vertical" size="large" style={{ width: '100%' }}>
            <Card title="Institution Search" size="small">
              <Form onFinish={searchInstitutions} layout="inline">
                <Form.Item name="institution_query" label="Institution Name" rules={[{ required: true }]}>
                  <Input 
                    placeholder="e.g., Stanford University, MIT (use full name recommended)" 
                    style={{ width: 280 }} 
                  />
                </Form.Item>
                <Form.Item name="inst_country" label="Country">
                  <Select placeholder="Select Country" style={{ width: 120 }}>
                    <Option value="US">USA</Option>
                    <Option value="CN">China</Option>
                    <Option value="GB">UK</Option>
                    <Option value="JP">Japan</Option>
                    <Option value="DE">Germany</Option>
                  </Select>
                </Form.Item>
                <Form.Item name="inst_type" label="Institution Type">
                  <Select placeholder="Select Type" style={{ width: 150 }}>
                    <Option value="education">Educational</Option>
                    <Option value="company">Company</Option>
                    <Option value="healthcare">Healthcare</Option>
                    <Option value="government">Government</Option>
                  </Select>
                </Form.Item>
                <Form.Item>
                  <Button type="primary" htmlType="submit" loading={loading}>
                    <SearchOutlined /> Search Institutions
                  </Button>
                </Form.Item>
              </Form>
            </Card>

            {institutionResults.length > 0 && (
              <Card title={`Institution Search Results (${institutionResults.length})`}>
                <Table
                  dataSource={institutionResults}
                  columns={institutionColumns}
                  rowKey="id"
                  pagination={{ pageSize: 10 }}
                  size="small"
                />
              </Card>
            )}

            {institutionProfile && (
              <Card title={`${institutionProfile.institution?.name} - 研究概况`}>
                <Row gutter={16}>
                  <Col span={6}>
                    <Statistic 
                      title="总论文数" 
                      value={institutionProfile.total_papers} 
                      prefix={<BookOutlined />}
                    />
                  </Col>
                  <Col span={6}>
                    <Statistic 
                      title="总引用数" 
                      value={institutionProfile.total_citations} 
                      prefix={<LineChartOutlined />}
                    />
                  </Col>
                  <Col span={6}>
                    <Statistic 
                      title="平均引用" 
                      value={institutionProfile.average_citations} 
                      precision={1}
                    />
                  </Col>
                  <Col span={6}>
                    <Statistic 
                      title="开放获取率" 
                      value={institutionProfile.open_access_ratio * 100} 
                      precision={1}
                      suffix="%"
                    />
                  </Col>
                </Row>
                <Divider />
                <Title level={5}>主要研究领域</Title>
                <Space wrap>
                  {institutionProfile.top_research_areas?.slice(0, 15).map((area: [string, number], index: number) => (
                    <Tag key={index} color="blue">
                      {area[0]} ({area[1]})
                    </Tag>
                  ))}
                </Space>
              </Card>
            )}
          </Space>
        </TabPane>

        <TabPane 
          tab={<Space><TeamOutlined />Collaboration Network</Space>} 
          key="collaboration"
        >
          {collaborationNetwork ? (
            <Card title="Author Collaboration Network Analysis">
              <Row gutter={16} style={{ marginBottom: 16 }}>
                <Col span={8}>
                  <Statistic 
                    title="Total Collaborators" 
                    value={collaborationNetwork.total_collaborators} 
                    prefix={<TeamOutlined />}
                  />
                </Col>
                <Col span={8}>
                  <Statistic 
                    title="Papers Analyzed" 
                    value={collaborationNetwork.total_papers_analyzed} 
                    prefix={<BookOutlined />}
                  />
                </Col>
              </Row>
              
              <Title level={5}>Frequent Collaborators</Title>
              <Collapse>
                {collaborationNetwork.frequent_collaborators?.slice(0, 10).map((collab: any, index: number) => (
                  <Panel 
                    header={
                      <Space>
                        <Text strong>{collab.name}</Text>
                        <Tag color="green">{collab.collaboration_count} collaborations</Tag>
                        <Tag color="blue">{collab.total_citations} total citations</Tag>
                      </Space>
                    } 
                    key={index}
                  >
                    <Title level={5}>Recent Collaborations</Title>
                    {collab.recent_collaborations?.slice(0, 5).map((paper: any, idx: number) => (
                      <div key={idx} style={{ marginBottom: 8 }}>
                        <Text>{paper.title}</Text>
                        <br />
                        <Space>
                          <Tag>{paper.year}</Tag>
                          <Text type="secondary">Citations: {paper.citations}</Text>
                        </Space>
                      </div>
                    ))}
                  </Panel>
                ))}
              </Collapse>
            </Card>
          ) : (
            <Card>
              <Text type="secondary">Please first select an author from the Author Search tab to view their collaboration network</Text>
            </Card>
          )}
        </TabPane>
      </Tabs>
    </Card>
  );
};

export default OpenAlexSearch;
