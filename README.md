# 基于 LangGraph 的多智能体酒店经营分析平台

基于 **FastAPI + LangGraph** 的对话式数据分析平台：用户用自然语言提问，
系统自动路由到「知识库检索 / 数据库查询 / 图表生成 / 发邮件 / 直接对话」，
以 SSE 流式返回分析结论与 ECharts 图表。

## 功能特性

- **智能路由**：LLM 按语义把问题分流到 6 个处理分支
- **NL2SQL 查库**：自然语言转 SQL 查询 MySQL 酒店业务库，`SQLQuestionAgent` 多轮 tool_call 自我纠错
- **RAG 检索**：DashScope embedding + 混合检索（BM25/向量）+ rerank，从知识库召回表结构与指标口径，约束回答不编造
- **ECharts 图表**：`EchartsAgent` 自动生成可渲染图表（柱状图 / 折线图 / 饼图等）
- **HITL 发邮件**：先起草邮件（主题 + 正文）并 `interrupt` 挂起，用户确认后才真正发送
- **多轮记忆**：Redis Checkpointer 持久化会话，重启不丢；历史过长自动压缩
- **JWT 鉴权**：登录后签发 Token，按用户隔离对话与缓存
- **流式输出**：SSE 逐字推送，并带「查询 / 画图 / 撰写」实时进度提示

## 技术架构

```
app/
├── main.py                  FastAPI 入口（lifespan 建图 + Checkpointer.asetup）
├── ai/
│   ├── model/               模型封装（主模型 + 路由轻量模型，单例）
│   ├── schemas/             结构化输出定义（route / chart / 各 tool 出参）
│   ├── tool/                工具：mysql / rag / data_calc / send_email
│   ├── graph/               LangGraph 图：state / build / context_compressor
│   ├── nodes/               10 个节点（见下）
│   └── agent/               智能体：SQLQuestionAgent / EchartsAgent / AnlyzeAgent / EmailDispatcher
├── api/
│   ├── auth/                登录与 JWT 签发
│   ├── chat/                SSE 流式问答接口
│   └── schema/              接口请求模型
└── static/                  前端页面（聊天界面 + 进度条 + ECharts）
```

图的 10 个节点：`summarize`（历史压缩）、`route`（意图路由）、
`rag` / `db` / `chart`（取数与画图）、`clarify`（信息不足反问）、
`system_draft` / `system_send`（邮件 HITL）、`writer`（综合撰写）、`chat`（直答）。

数据流：

```
用户问题 → (summarize) → route → 条件边分流
        ├─ rag   ─┐
        ├─ db     ├→ writer → SSE 流式返回
        ├─ chart ─┘
        ├─ system_draft → system_send（interrupt 等确认）→ writer
        ├─ clarify → END（反问）
        └─ chat    → END（直答）
```

## 快速开始

### 1. 环境依赖

Python 3.12：

```bash
pip install -r requirements.txt
```

### 2. 配置

复制 `.env.example` 为 `.env` 并填入真实配置：

```bash
cp .env.example .env
```

需要：模型 API Key（OpenAI 兼容网关 + DashScope）、MySQL 连接、Redis 地址、发信邮箱（SMTP 授权码）。

### 3. 启动依赖服务

- **MySQL**：酒店业务库（默认库名 `hotel`）
- **Redis**：LangGraph Checkpointer 持久化与 RAG 向量库

### 4. 启动服务

```bash
python app/main.py
```

访问 `http://localhost:8000` 打开前端，或 `http://localhost:8000/docs` 查看接口文档。

也可用 Docker 一键部署：

```bash
docker build -t data-analysis-platform .
docker run -p 8000:8000 --env-file .env data-analysis-platform
```

## 说明

- 图负责编排（路由 / 记忆 / 压缩 / 缓存 / 重试 / HITL），节点内调用独立智能体完成具体任务。
- `db` 节点最重：先 RAG 召回相关表结构，再由 `SQLQuestionAgent` 带工具多轮生成并校正 SQL，最后查库。
- Checkpointer 优先 Redis（重启不丢对话），连接失败自动降级内存。
- 缓存按「用户 + 改写后问题」生成 key，避免不同用户命中同一快照。
