实体表 (共7个)
1. Papers
  1. 建表SQL（字段后面的注释是对应数据路径，数据来源是arxiv api或论文pdf/bbl）
create table papers (
    id int primary key,   
    paper_title text,                 --  [*].authors[*].name
    published date,                   --  [*].published
    updated date,                     --  [*].updated
    abstract text,                    --  [*].summary
    doi text,                         --  [*].doi  (一般arxiv api不返回对应 entry 需另取数据源)
    pdf_source text,                  --  
    arxiv_entry text unique,          --  [*].links.pdf的数字部分
    unique (paper_title, published)
);
  2. 设计说明：
    1. "doi"字段在arxiv api 以及返回的bbl中几乎不存在，作为预留字段，有合适数据源可补充维护。字段类型改为TEXT以支持更长的DOI。
    2. 数据唯一性：依赖复合键(paper_title, published)，仅凭"paper_title"似乎不够严谨，因为同一篇论文可修改提交多次。
    3. 将论文的category以及keywords从papers表中分离，因为不论paper与category还是paper与keyword均是多对多关系，统一存储存在大量数据冗余。
2. Authors
  1. 建表SQL
create table authors (
    id int primary key,
    author_name_en text,               --  [*].authors[*].name
    author_name_cn text,               -- 需外部数据源
    email varchar(100),               -- pdf
    orcid varchar(100),               -- 需外部数据源
    citations int,                    -- 引用次数
    h_index int,                      -- H指数
    i10_index int                     -- I10指数
);
  2. 设计说明：
    1. 数据唯一性：authors表的数据唯一性较为困难，email和orcid字段移除了unique约束，因为存在同一作者多个邮箱/ORCID以及多人共用同一邮箱的情况。
    2. 新增学术指标字段：citations（引用次数）、h_index（H指数）、i10_index（I10指数）用于存储作者的学术影响力指标。
3. Affliation
  1. 建表SQL
create table affiliations (
    id int primary key,           
    aff_name text unique,              --  [*].authors[*].affiliation (一般arxiv api不返回此 entry 需另取数据源)
    aff_type enum('university', 'research_institute', 'other') not null, -- 设计逻辑判断
    country text,                      -- 需外部数据源
    state text,                        -- 需外部数据源
    city text                          -- 需外部数据源
);
  2. 说明：
    1. 数据唯一性通过"aff_name"字段实现；在业务层进行规范化去重：忽略大小写与空白字符差异（例如 "Zhejiang University" 与 "zhejiangUniversity" 视为同一机构）。
    2. "aff_type enum"字段用来区分作者所属机构是为大学还是公司研究所；"rank_system"用来表示对机构排名所参考的标准，因为大学有QS排名等，而QS不适用于公司排名；"rank_value"表示在指定的排名体系中的位次，暂定类型为varchar，也可换成int。
4. Ranking_systems
  1. 建表SQL
create table ranking_systems (
    id int primary key,    
    system_name text unique,           -- 需外部数据源
    update_frequency int               -- 需外部数据源，更新频率（年）
);
  2. 说明：
    1. 字段"system_name"表示排名系统名称（如'QS'）；字段"update_frequency"表示排名系统的更新频率（以年为单位），比如QS一年一评则为1。
5. Keywords
  1. 建表SQL
create table keywords (
    id int primary key,
    keyword text unique                --  [*].links[*].pdf 中提取
);
  2. 说明：
    1. 数据唯一性用"keyword"表示即可，实际上主键也可以直接设置为"keyword"，不过为了统一建表风格，还是添加了额外的自增主键"keyword_id"。
6. Categories
  1. 建表SQL
create table categories (
    id int primary key,
    category text unique               --  [*].category[*][$schema]
);
  2. 说明：
    1. 数据唯一性用"category"表示即可，实际上主键也可以直接设置为"category"，不过为了统一建表风格，还是添加了额外的自增主键"category_id"。
7. people_verified
  1. 建表SQL
create table people_verified (
    id int primary key,
    name_en text,                      -- 需外部数据源
    name_cn text                       -- 需外部数据源
);
  2. 说明：
    1. 此表暂不插入任何数据。
关联表 （共5个）
1. author_paper
  1. 建表SQL 
create table author_paper (
    id int primary key,
    author_id int,
    paper_id int,
    author_order int not null,         --  pdf
    is_corresponding boolean,          --  pdf
    FOREIGN KEY (author_id) REFERENCES authors(id) ON DELETE CASCADE,
    FOREIGN KEY (paper_id) REFERENCES papers(id) ON DELETE CASCADE,
    unique (author_id, paper_id)
);
  2. 说明：
    1. 该关联表除了起到关联作用的字段外，还设计了"author_order"（第几作者）和"is_corresponding"（是否是通讯）字段。
    2. 数据唯一性依赖复合键(author_id, paper_id)实现
2. author_affiliation
  1. 建表SQL
create table author_affiliation (
    id int primary key,
    author_id int,
    affiliation_id int,
    role text,                         -- 原 work 字段，改为更通用的角色描述
    department text,                   -- 部门信息
    start_date date,                   -- 在该机构的起始时间（可为空）
    end_date date,                     -- 在该机构的截止时间（可为空）
    latest_time date,                  -- 该作者以此机构发表论文的"最近一次"时间
    FOREIGN KEY (author_id) REFERENCES authors(id) ON DELETE CASCADE,
    FOREIGN KEY (affiliation_id) REFERENCES affiliations(id) ON DELETE CASCADE,
    unique (author_id, affiliation_id)
);
  2. 说明：
    1. 该表只起到关联作用；新增 `role`（TEXT）用于记录作者在机构内的角色/职位信息；新增 `department`（TEXT）用于记录作者所在的具体部门；新增 `start_date` 与 `end_date` 表示在该机构的起止时间（若未知可为空）。
    2. `latest_time` 表示"该作者以该机构署名发表论文的最近一次日期"；当前抓取流程未填充此字段，后续落库或对齐步骤需要注意补写（可由论文 `published` 聚合得出）。
    3. 数据唯一性依赖复合键(author_id, affiliation_id)实现
3. paper_category
  1. 建表SQL
create table paper_category (
    id int primary key,
    paper_id int,
    category_id int,
    FOREIGN KEY (paper_id) REFERENCES papers(id) ON DELETE CASCADE,
    FOREIGN KEY (category_id) REFERENCES categories(id) ON DELETE CASCADE,
    unique (paper_id, category_id)
);
  2. 说明：
    1. 该表只起到关联作用，无其他额外信息
    2. 数据唯一性依赖复合键(paper_id, category_id)实现
4. paper_keyword
  1. 建表SQL
create table paper_keyword (
    id int primary key,
    paper_id int,
    keyword_id int,
    FOREIGN KEY (paper_id) REFERENCES papers(id) ON DELETE CASCADE,
    FOREIGN KEY (keyword_id) REFERENCES keywords(id) ON DELETE CASCADE,
    unique (paper_id, keyword_id)
);
  2. 说明：
    1. 该表只起到关联作用，无其他额外信息
    2. 数据唯一性依赖复合键(paper_id, keyword_id)实现
5. affiliation_rankings
  1. 建表SQL
create table affiliation_rankings (
    id int primary key,       
    aff_id int,                        
    rank_system_id int,                
    rank_value int,                    -- 需外部数据源，排名数值
    rank_year int,                     -- 需外部数据源
    FOREIGN key (aff_id) REFERENCES affiliations(id) ON DELETE CASCADE,
    FOREIGN key (rank_system_id) REFERENCES ranking_systems(id) ON DELETE CASCADE,
    UNIQUE key (aff_id, rank_system_id, rank_year)
);
  2. 说明：
    1. 除了起到关联作用的字段，字段"rank_value"表示该机构在"rank_year"年在该排名系统中的排名，字段类型改为INT以存储数值型排名。
    2. 数据唯一性依赖复合键(aff_id, rank_system_id, rank_year)实现
6. author_people_verified
  1. 建表SQL
create table author_people_verified (
    id int primary key,       
    author_id int,                        
    people_verified_id int,                
    FOREIGN key (author_id) REFERENCES authors(id) ON DELETE CASCADE,
    FOREIGN key (people_verified_id) REFERENCES people_verified(id) ON DELETE CASCADE,
    UNIQUE key (author_id, people_verified_id)
);