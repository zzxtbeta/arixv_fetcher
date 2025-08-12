实体表 (共7个)
1. Papers
  1. 建表SQL（字段后面的注释是对应数据路径，数据来源是arxiv api或论文pdf/bbl）
create table papers (
    id int primary key,   
    paper_title varchar(300),         --  [*].authors[*].name
    published date,                   --  [*].published
    updated date,                     --  [*].updated
    abstract text,                    --  [*].summary
    doi varchar(100) unique,          --  [*].doi  (一般arxiv api不返回对应 entry 需另取数据源)
    pdf_source varchar(100),          --  
    arxiv_entry varchar(100) unique,  --  [*].links.pdf的数字部分
    unique (paper_title, published)
);
  2. 设计说明：
    1. “doi”字段在arxiv api 以及返回的bbl中几乎不存在，作为预留字段，有合适数据源可补充维护。
    2. 数据唯一性：依赖复合键(paper_title, published)，仅凭“paper_title”似乎不够严谨，因为同一篇论文可修改提交多次。
    3. 将论文的category以及keywords从papers表中分离，因为不论paper与category还是paper与keyword均是多对多关系，统一存储存在大量数据冗余。
2. Authors
  1. 建表SQL
create table authors (
    id int primary key,
    author_name_en varchar(100),       --  [*].authors[*].name
    author_name_cn varchar(100),       -- 需外部数据源
    email varchar(100) unique,         -- pdf
    orcid varchar(100) unique          -- 需外部数据源
);
  2. 设计说明：
    1. 数据唯一性：authors表的数据唯一性较为困难，可用来设为unique的字段“orcid”均缺失严重，这里采用“email”作为唯一性约束，但是还是存在同一作者多个邮箱以及多人共用同一邮箱的情况（尽管是少数），所以这里的设计存在问题。
3. Affliation
  1. 建表SQL
create table affiliations (
    id int primary key,           
    aff_name varchar(300) unique,      --  [*].authors[*].affiliation (一般arxiv api不返回此 entry 需另取数据源)
    aff_type enum('university', 'research_institute', 'other') not null, -- 设计逻辑判断
    country varchar(100),              -- 需外部数据源
    state varchar(100),                -- 需外部数据源
    city varchar(100)                  -- 需外部数据源
);
  2. 说明：
    1. 数据唯一性通过“aff_name”字段实现
    2. "aff_type enum"字段用来区分作者所属机构是为大学还是公司研究所；“rank_system”用来表示对机构排名所参考的标准，因为大学有QS排名等，而QS不适用于公司排名；“rank_value”表示在指定的排名体系中的位次，暂定类型为varchar，也可换成int。
4. Ranking_systems
  1. 建表SQL
create table ranking_systems (
    id int primary key,    
    system_name varchar(100) unique,   -- 需外部数据源
    update_frequency varchar(50)       -- 需外部数据源
);
  2. 说明：
    1. 字段“system_name”表示排名系统名称（如'QS ）；字段“update_frequency”表示排名系统的更新频率，比如QS一年一评
5. Keywords
  1. 建表SQL
create table keywords (
    id int primary key,
    keyword varchar(300) unique        --  [*].links[*].pdf 中提取
);
  2. 说明：
    1. 数据唯一性用“keyword”表示即可，实际上主键也可以直接设置为“keyword”，不过为了统一建表风格，还是添加了额外的自增主键“keyword_id”。
6. Categories
  1. 建表SQL
create table categories (
    id int primary key,
    category varchar(300) unique           --  [*].category[*][$schema]
);
  2. 说明：
    1. 数据唯一性用“category”表示即可，实际上主键也可以直接设置为“category”，不过为了统一建表风格，还是添加了额外的自增主键“category_id”。
7. people_verified
  1. 建表SQL
create table people_verified (
    id int primary key,
    name_en varchar(300),           -- 需外部数据源
    name_cn varchar(300)            -- 需外部数据源
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
    1. 该关联表除了起到关联作用的字段外，还设计了“author_order”（第几作者）和“is_corresponding”（是否是通讯）字段。
    2. 数据唯一性依赖复合键(author_id, paper_id)实现
2. author_affiliation
  1. 建表SQL
create table author_affiliation (
    id int primary key,
    author_id int,
    affiliation_id int,
    latest_time date,                   -- 需外部数据源
    work varchar(100),                  -- 需外部数据源
    FOREIGN KEY (author_id) REFERENCES authors(id) ON DELETE CASCADE,
    FOREIGN KEY (affiliation_id) REFERENCES affiliations(id) ON DELETE CASCADE,
    unique (author_id, affiliation_id)
);
  2. 说明：
    1. 该表只起到关联作用，无其他额外信息 （修改说明：添加字段"latest_time"，表示该作者在这个机构最新发表的论文的时间；添加字段"work"，表示该author在此机构的职位是什么）
    2. 数据唯一性依赖复合键(author_id, affiliation_id)实现
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
    rank_value varchar(50),            -- 需外部数据源
    rank_year int,                     -- 需外部数据源
    FOREIGN key (aff_id) REFERENCES affiliations(id) ON DELETE CASCADE,
    FOREIGN key (rank_system_id) REFERENCES ranking_systems(id) ON DELETE CASCADE,
    UNIQUE key (aff_id, rank_system_id, rank_year)
);
  2. 说明：
    1. 除了起到关联作用的字段，字段“rank_value”表示该机构在“rank_year”年在该排名系统中的排名
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