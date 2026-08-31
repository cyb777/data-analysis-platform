# 基于 LangGraph 与 RAG 的多智能体问答平台

基于 **FastAPI** 的对话式智能问答平台：用户用自然语言提问，
系统自动路由到「知识库检索 / 数据库查询 / 图表生成 / 直接对话」之一，并以流式方式返回答案与图表。

## 功能特性

- **智能路由**：LLM 按语义判断问题类型，分流到不同处理节点
- **NL2SQL 查库**：自然语言转为 SQL 查询 MySQL，仅限 `SELECT`（代码级只读护栏）
- **RAG 检索**：根据问题从知识库召回相关表结构与指标口径，约束回答不编造
- **ECharts 图表**：自动生成可渲染的图表 JSON（柱状图 / 折线图 / 饼图）
- **多轮记忆**：同一会话（thread_id）可上下文连贯追问
- **流式输出**：基于 SSE（Server-Sent Events）逐字推送
- **邮箱验证码登录 / 注册**

## 技术架构

```
app/
├── main.py                  FastAPI 入口（lifespan 建图 + 路由注册）
├── ai/
│   ├── model/               模型封装（单例）
│   ├── schema/              结构化输出定义（Route / ChartData / Email ...）
│   ├── tool/                工具（mysql 查询 / 邮件发送）
│   ├── rag/                 RAG 知识库（分块 → 向量化 → Redis）
│   ├── graph/               LangGraph 图（state / nodes / build）
│   └── agent/               四个智能体（sql / echarts / analyze / system）
├── api/
│   ├── chat/                SSE 流式问答接口
│   └── system/              邮箱验证码登录 / 注册接口
└── static/                  前端页面（聊天 + 登录）
```

数据流：`用户问题 → 路由节点 → 条件边分流 → (rag | db | chart) → 综合回答节点 → SSE 流式返回`

## 快速开始

### 1. 环境依赖

```bash
pip install -r requirements.txt
```

### 2. 配置

复制 `.env.example` 为 `.env` 并填入真实配置：

```bash
cp .env.example .env
```

需要：模型 API Key、MySQL 连接、Redis 地址、发信邮箱。

### 3. 启动依赖服务

- **Redis**：RAG 向量库与验证码缓存都依赖它
- **MySQL**：提前建好 `agent` 库及 `sales` / `customer` / `orders` 等表（表结构见 `docs/分析平台知识库.txt`）

### 4. 启动服务

```bash
python app/main.py
```

访问 `http://localhost:8000` 打开前端，或 `http://localhost:8000/docs` 查看接口文档。

## 说明

- 图内的节点会调用独立智能体完成具体任务，图负责编排（路由 / 记忆 / 缓存 / 重试）。
- 数据库工具提供两个版本：`mysql_tool`（可执行任意 SQL，用于注册等写入）与
  `sql_query_tool`（只读护栏版，非 `SELECT` 语句直接拦截，供智能体使用）。
- 记忆使用内存存储（`InMemorySaver`），服务重启后历史会话即丢失。
