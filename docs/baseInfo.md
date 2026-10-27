# 项目基本信息

## 一、项目目录及框架定义

```
D:\data-analysis-platform
|   .env <环境变量：API Key、数据库、邮箱、Redis 配置（敏感文件，不上传 Git）>
|   requirements.txt <Python 依赖>
|   Code_Wiki.md <代码知识库，人类维护>
|
+---app <程序模块 — 整个系统放置于此>
|   |   main.py <FastAPI 服务主入口：lifespan 建图、CORS、路由注册、静态文件托管>
|   |   __init__.py
|   |
|   +---ai <AI 核心模块 — 多智能体、RAG、工具、Schema>
|   |   |   __init__.py
|   |
|   |   +---agent <智能体定义与编排（4 个：sql_question / echarts / anlyze / email_dispatcher；registry.py 统一基类 BaseToolAgent + invoke_with_structured_retry 结构化重试）>
|   |   +---graph <LangGraph 图：state / build（缓存+重试+记忆装配）>
|   |   +---mem <记忆包（mem_43 对话冷层）：history（冷层向量库：块原文入库 embed_turns / 语义回查 mem_recall；tag=sha1(thread_id) 哈希）/ compress（分块判断+块压缩+事实合并）/ recall（两个不耦合入口：node_history_text 只拼热层+温层、recall_text 只管冷层回查——只有 chat 调它，冷层回查唯一责任方）>
|   |   +---model <模型封装（火山方舟 ark-code-latest）>
|   |   +---nodes <LangGraph 节点函数（与 graph/ 平级，共 10 个）：summarize / route / rag / db / chart / clarify / system_draft / system_send / writer / chat；对比类统一走 chart 出图>
|   |   +---rag <RAG 包：builder（建库管线：根目录 rag_corpus/ 多文档 → 分块打 tag → 幂等增量入库 + BM25 索引）/ retriever（在线检索：向量+BM25 双路召回 → RRF 融合 → gte-rerank-v2 精排，逐级降级；metadata tag 2 类 business/hotel）>
|   |   +---schemas <Pydantic 数据形状：llm_* 前缀=LLM 输出（4：route/chart/clarify/email），tool_* 前缀=工具入参（2：calc/sql）>
|   |   \---tool <多工具（3 个）：mysql_tool（连接池查库 + describe_table + 只读护栏 + SQL 强制 LIMIT 兜底）/ data_calc_tool（精确计算）/ email_material_tool（邮件素材三件套 @tool + SMTP 直发/留痕——后者不挂 @tool，发信时机由图编排定死）>
> **检索的两种调用姿势**：业务节点（db/chart/email_dispatcher）走 `build_schema_block`（tag="business"）——把检索当系统前置动作，确保 SQL 生成必查口径；rag 节点直调 `retriever.retrieve_schema`（tag="hotel"）只召酒店业务通识。建库侧幂等增量：确定性 key + manifest 台账，未变文件 0 次 embedding、重启不翻倍。|
|   |
|   +---api <接口层 — 对外提供 RESTful 接口>
|   |   |   __init__.py
|   |   |
|   |   +---auth <auth 领域：jwt.py（HS256 + 7 天；payload=employee_id+level+iat+pwd_sig，改密旧 token 自动 401；JWT_SECRET 未配 fail-fast）+ auth_router.py（员工编号+密码登录 / change_password / bind_email，无公开注册）+ password.py（PBKDF2-HMAC-SHA256 10 万迭代）>
|   |   +---chat <聊天接口：SSE 流式问答（/chat + /chat/resume + /chat/history；6 种帧：text / chart / clarify / system / status / confirm）>
|   |   \---schema <接口请求/响应数据模型>
|   |
|   \---static <前端静态资源>
|           index.html <单页前端骨架：HTML 结构 + link/script 引用（CSS/JS 已外置）>
|           +---css
|           |       style.css <设计令牌 + 全部页面样式>
|           \---js
|                   app.js <全部前端逻辑：SSE 流式渲染 / 图表 / 复制下载 / 登录等>
|                   +---lib
|                           echarts.min.js <ECharts 本地 vendoring（本地优先 + CDN 多源兜底）>
|
+---database <数据库脚本，schema.sql 为唯一权威来源>
|       schema.sql <hotel 库物理 17 张 = 可查 16 + 认证 1：15 业务表（hotel/room_type/guest/reservation/stay_record/channel/payment/expense/restaurant/meal_order/menu_item/service_order/employee/service_record/review_complaint）+ 邮件留痕表 notification_record + 纯认证表 user_info（employee_id + PBKDF2 哈希，不在 LLM 可查面）；employee 主键即员工编号（入职年4+区域码2+部门码2+序号2），带 email（UNIQUE 可空）/level（五级）；无真实外键，靠索引字段 JOIN>
|       seed_hotel.py <酒店种子数据：10 门店 × 2024-08~2027-08 共 535 万行业务明细；幂等（跑 schema + 全插）；员工 391 人全编号化、管理岗 42 人预绑邮箱（老板=boss@hotel.demo 占位），在职全员认证账号（初始密码 123456、独立盐）；notification_record 不造数，靠运行时写入>
|       schema_extension.sql、schema_extension_v2.sql、seed_v2.sql <旧电商版遗留脚本，已废弃，不适用于 hotel 库>
|
+---test <测试脚本（按功能拆分，全部可独立直接运行；产物统一落 output/）>
|       full_regress_v156.py <全量回归：离线断言 + 在线 SSE>
|       e2e_test.py <端到端（end-to-end）：11 推荐问题真打服务，需先启服务；结果落 output/e2e_result.txt>
|       test_route.py <Route schema 约束 / 权限门分级（离线）>
|       test_memory.py <三层记忆 / 压缩节奏双坐标 / 延迟截断 / 哨兵守卫 / chat 唯一回查（离线）>
|       test_db.py <MySQL 工具 / 只读护栏 / data_calc 计算（离线）>
|       test_chart.py <图表智能体全链路，真出图（离线）>
|       test_rag.py <RAG 混合检索 / Schema 召回（需建向量库）>
|       test_ragas.py <RAGAS 四指标评测：知识库问答链 12 题（忠实度/相关性/上下文精确率/召回），需先开 Redis；检索+生成结果缓存 output/ragas_raw.json，明细落 output/ragas_result.csv>
|       test_email.py <send_email_direct 直发冒烟（会真实发信）>
|       test_auth.py <编号登录 / PBKDF2 / 改密（旧 token 401）/ 绑邮箱（离线）>
|       check_login_gate.py <前端登录闸 playwright 验证（无 token 弹框/关框/拦截），截图落 output/，需先启服务>
|       +---debug <可复用调试工具：mem_inject.py 灌假历史触发真实压缩 + 真发验证 / read_state.py 直读 checkpoint 验证压缩结果>
|       \---output <跑分/结果/截图产物：ragas_raw.json、ragas_result.csv、e2e_result.txt、login_gate_check.png、mem_inject_result.txt>
+---rag_corpus <RAG 语料目录（读取全部 .md/.txt 入库；.manifest.json=增量建库台账；tags.json=文件级 tag 登记表，未登记默认 hotel）>
|       表结构.txt <表范围 + 16 张可查表结构 + 指标口径 + 查询规范（tag=business，tags.json 登记，SQL 侧字典）>
|       业务知识通识.txt <酒店业务通识 12 节（tag=hotel，未登记走默认）>
|       tags.json <文件级 tag 登记表（不入库：glob 只认 .md/.txt；business 才登记，hotel 免登记）>
\---docs <项目文档目录（.gitignore 白名单：仅 4 份主文档）>
|       baseInfo.md <本文件：项目框架基础信息，用于 AI 理解项目结构，人类动态维护>
|       baseCoding.md <编码规范与质量约束，人类维护>
|       baseMem.md <开发记忆：协作约定 + 关键决策结论，AI 主动维护（含文档自维护协议）>
|       devPlan.md <开发计划与进度跟踪，AI 自动维护>
|       \---学习文件 <学习与面试文档，不入 Git>
                01面试观看顺序.md <按 JD 定制的面试文档观看顺序，每份 JD 换一份>
                02项目面试八股.md <面试速记卡：8功能4段式+量化数据+简历整段可抄>
                03部分代码讲解.md <关键机制深讲：interrupt / 结构化输出 / RAG 三段式 / 缓存 key_func / 三层记忆 / 接口时序>
                04实习生基础八股.md <基础八股：Redis / MySQL / Python / HTTP·FastAPI·JWT / Docker / Agent 概念>
                05lectureNotes.md <早期学习笔记，内容已被 02 / 03 覆盖>
```

## 二、项目基础要求

- **项目文件编码**：全部用 UTF-8 保存。
- **服务端口**：8000（uvicorn 默认），前端静态页面访问 `http://localhost:8000`。
- **前端开发端口**：8081（CORS 已配置允许 `localhost:8081` 和 `127.0.0.1:8081`）。
- **建议终端**：Windows Terminal（Cmd 模式 / PowerShell 模式）。
- **开发环境**：venv 或 conda 环境（需安装 requirements.txt 依赖）。
- **项目运行**：`python app/main.py`（uvicorn 启动，reload=False）。
- **服务停止**：`Ctrl + C` 停止。
- **Python 环境**（**用户原话 57 锁版**）：**必须用** `D:\Anaconda3_env\envs\lang_cg\python.exe`（conda 环境 lang_cg），**别用 base 环境**（缺 `langchain_community` / `langchain_redis`）。所有脚本/测试启动方式：`& "D:/Anaconda3_env/envs/lang_cg/python.exe" "d:/data-analysis-platform/app/main.py"`，**PowerShell 兼容的 `&&` 不可用**。
- **前置依赖**：Redis 必须开着（RAG 向量库 + Checkpointer 持久化 + 记忆冷层入库都用它）。

## 三、项目技术栈

| 层级 | 技术 |
|:--|:--|
| 后端框架 | FastAPI + Uvicorn |
| AI 编排 | LangChain + LangGraph（多智能体、条件边路由、Checkpoint 记忆、对话压缩节点）|
| 大模型 | 火山方舟 Coding Plan（主模型 `ark-code-latest` + `/api/coding/v3` 端点）<br>**路由专用轻量模型 `doubao-seed-2.0-lite`**（`ROUTE_MODEL_NAME`：主模型走 `with_structured_output` 单次约 133s，换轻量模型后 1.5~2.9s）|
| RAG | Redis 向量库，MarkdownTextSplitter 分块 + DashScope 向量化（chunk_size=600 / overlap=120 / metadata tag 2 类 business+hotel）<br>**三段式检索**：向量 + BM25 双路各召回 10 条 → RRF 融合 → gte-rerank-v2 精排取前 5（2026-09-13 直调 SDK 真正接通，wrapper 锁死 v1 且无权限）。<br>BM25 补向量短板（表名列名是专有名词只有字面没有语义），实测召回率 81% → 100%；BM25/rerank 任一不可用都自动降级。<br>**建库幂等增量（2026-10-19）**：确定性 key + manifest 台账，未变文件 0 次 embedding、重启不翻倍；语料目录为根目录 rag_corpus/，支持多文档。<br>**效果量化（2026-10-16 RAGAS，12 题知识库问答链）**：忠实度 0.96 / 相关性 0.90 / 上下文召回 0.92 / 精确率 0.88（test/test_ragas.py） |
| NL2SQL | RAG 检索表结构（列名白名单）→ LLM 生成 SQL → Pydantic 结构化输出 |
| 数据库 | MySQL（hotel 库物理 17 张 = 可查 16 + 认证 1）|
| 缓存 | Redis（向量库 kb_43 / 记忆冷层 mem_43 + Checkpointer）+ LangGraph `InMemoryCache` 节点缓存（自定义 key_func：只取 `user_id|改写后问题`，多轮可命中、跨用户隔离）<br>Checkpointer 为 **AsyncRedisSaver**（对话状态 Redis 持久化，重启不丢；Redis 连不上自动退 InMemorySaver——窄故障面，Redis 全挂会更早死于启动期建库） |
| 流式响应 | SSE（Server-Sent Events，6 种帧）：前端 fetch POST 手写 SSE（`getReader()` 读响应流，`AbortController` 主动断开），后端 `stream_mode=["updates","messages"]` 混合模式**边跑边推**，chart 帧不再等整图跑完<br>`subgraphs=True`：AnlyzeAgent 由 `create_agent` 创建是**嵌套子图**，不开这个开关 LangGraph 不转发子图 token。开启后 text 帧逐字流出 |
| 鉴权 | **JWT（HS256 + 7 天过期）**：员工编号+密码登录签发（无公开注册）；payload = employee_id + level + iat + pwd_sig（改密后旧 token 自动 401，零吊销组件）；JWT_SECRET 未配置启动即拒（fail-fast）。/chat 走 optional（无 token 保留体验模式，匿名会话前端 sessionStorage UUID 隔离）；另提供 `get_required_user` 供强制登录接口用。/chat 与 /chat/resume 均为 POST，token 走标准 `Authorization: Bearer` 头 |
| 邮件 | QQ 邮箱 SMTP（`send_email_direct` 直发，跳过 LLM；收件人查 employee——`position OR employee_name` 一条查询按 level 分级，外部邮箱仅经理级；草稿即校验，HITL 确认后 system_send 三分支自写 answer 直连 END）|
| 前端 | 单页 HTML + 外置 CSS/JS（`:root` 设计令牌、暗色模式、进度步骤条、停止生成、图表下载 PNG）|
| 图表 | ECharts（前端渲染，本地 vendoring 优先 + CDN 多源兜底）|

## 四、核心业务流程

```
用户提问（前端）
    ↓
SSE 流式接口（app/api/chat，6 种帧：text / chart / clarify / system / status / confirm）
    ↓
LangGraph 图（app/ai/graph）
    ↓
入口条件边：未压尾部 history[summary_upto:] 攒够 50 轮才进 summarize 压缩（轻量模型，每块 50 轮
           封存只追加），否则直接进 route。
           块提交三件套原子语义：压缩 → 原文 embedding 入 mem_43 → 全成才写 state；
           任一失败不写 state、置退避 600s（进程内字典）。history 延迟截断：
           入库后原文留作备份，攒到 100 轮上限才哨兵删最老一块；失败时未入库的一律不删（缓冲带）。
           冷层回查只在 chat 节点做（追问/指代/溯源类问题归 chat 承接）：mem_recall
           （query 取 rewritten_q or question，向量+rerank，无关键词闸门/无词面兜底）；
           route/writer/clarify 只调 node_history_text（拼热层+温层，不查），
           回查成本只落在 chat 这一条分支。
           热层注入 prompt 时每轮带【YYYY-MM-dd HH:mm】时间戳（首行带（现在：）锚点），引用历史可直接指时间。
    ↓
route 节点（轻量模型一次调用输出 {branch, rewritten_q}：
           分支路由 6 选 1 + 入口改写——追问结合历史改写成自包含问题，下游零感知。
           「回溯早期对话」类问题（引用自己早前说过的细节、回顾之前聊过的内容）prompt 里
           明确派 chat——回查能力只在 chat；指代能靠 rewritten_q 还原成自包含取数问题时照常派 db/chart。
           纯 LLM 判断（无关键词层），LLM 异常走顶层默认 chat（fail-safe 降级）；
           权限门：db/chart/system 均要经理级（level≥3），越权自写 answer 直连 END）
      ↑ 用 ROUTE_MODEL_NAME 轻量模型 + with_structured_output(Route) 的 Literal 枚举强约束
    ├─ 缺时间 → db/chart 智能体按「最近30天」自查并在答案注明（规则只写在两个 agent 的 prompt，无 state 字段）；
    ├─ 真模糊 / 用户不满 → clarify 节点（LLM 猜意图 → 反问 + 编号候选，纯文本走 answer；
    │    用户回"1"由 route 入口改写还原成完整问题；不查库，直连 END 不汇入 writer）
    ├─ 查业务数据 → db / chart 节点（用 rewritten_q 取数 + 检索）
    ├─ 对比类 → chart 节点（对比类统一出图，无独立 compare 节点）
    ├─ 发邮件/通知 → system_draft 节点（EmailDispatcher 起草即校验：写作 agent 自主编排素材三件套
    │    + 收件人一次查全，确认集=展示集，不发送）
    │    → system_send 节点（interrupt 挂起等用户点「确定发送」，HITL 人工断点；
    │       确认/取消/失败三分支均自写 answer 直连 END——确认才群发+落 notification_record）
    ├─ 自由问答 / 知识库 → rag 节点（tag_filter="hotel" 只召酒店业务通识）
    └─ 对话式追问（不用取数）→ chat 节点（最小提示词单次调用，直连 END 不汇入 writer）
    ↓
边跑边推（stream_mode=["updates","messages"] + subgraphs=True）：
    节点跑完即推 status 进度帧 → chart_json 一产出立刻推 chart 帧
    → writer/chat 节点文字 token 逐字流式推 text 帧 → 收尾补推 system 帧
    → system 分支挂起时推 confirm 帧，用户点击后 POST /chat/resume 从断点恢复推流
```

> State 共 15 个字段（`total=False` 无伪默认值），history 用自定义 reducer（`append_history`：常规追加 + 哨兵截断（`("__truncate__", keep:int)`，int 守卫防用户输入误触发））。history 仅未压尾部（热层），已压块原文在 mem_43 向量库（mem/ 包），checkpointer 体积有界。**thread_id 不进 state**——复用 `config["configurable"]["thread_id"]`（节点签名注入），legacy 老线程部署时一次性清 checkpoint 故无需 mem_v2 标记。

> **版本演进历史不在本文档。** 本文档只描述项目**现在**长什么样。
> 想知道「还有什么没做」看 [devPlan.md](file:///d:/data-analysis-platform/docs/devPlan.md)；
> 想知道「为什么这么设计」看 [baseMem.md](file:///d:/data-analysis-platform/docs/baseMem.md) 的关键技术决策段；
> 想知道「面试怎么讲」看 [02项目面试八股.md](file:///d:/data-analysis-platform/docs/学习文件/02项目面试八股.md)。

## 五、文档维护说明

**四个主文档各司其职，不要互相抄**（2026-09-11 用户要求：「每个文档让它做自己的功能就好了」）：

| 文档 | 唯一职责 | 维护者 | 不该放什么 |
|:--|:--|:--|:--|
| `baseInfo.md` | 项目**现在**长什么样（目录树 / 技术栈 / 业务流程） | AI 维护 | **版本演进流水账**（「从 X 改成 Y」） |
| `devPlan.md` | **还有什么没做**（未完成排最上面） | AI 维护 | 做完的复盘 |
| `baseMem.md` | 协作约定 + 关键决策的**结论** | AI 维护 | 诊断过程、对照实验数据 |
| `学习文件/02项目面试八股.md` | 面试怎么讲（量化数据 / 4 段式话术） | AI 维护 | 实现细节 |

其余：`baseCoding.md`（编码规范）、
`rag_corpus/` 语料 2 文件（`表结构.txt` 17 表+指标口径+查询规范 / `业务知识通识.txt` 业务通识，metadata tag 2 类 business/hotel，`tags.json` 文件级登记）、
`学习文件/`（学习与面试文档：01 观看顺序 / 02 面试八股 / 03 代码讲解 / 04 基础八股 / 05 学习笔记，不入 Git）。
AI 自身的文档维护协议（改完即更 / 会话必读 / 自查）见 [baseMem.md](file:///d:/data-analysis-platform/docs/baseMem.md) 协作约定第 9 条。

**一次改动做完只有三种去处**：变成 baseInfo 的「现状」、
变成 baseMem 的一行「决策结论」、或者直接删。**不保留完整过程。**
