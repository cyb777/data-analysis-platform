# 项目开发计划

> 本文档跟踪开发进度与待办事项，由 AI 自动维护。
> 人类可手动调整优先级或添加新需求。
>
> **文档结构约定（2026-09-11 用户要求）**：
> 「以后编写这个 devplan，把未完成写在上面」——
> **未完成 / 待拍板 / 待办永远排在文档最前面**，已完成、已归档一律往后沉。
> 打开文档第一眼看到的必须是「还有什么没做」，而不是「做过什么」。

---

## 当前状态

**版本**：v2.x（连锁酒店管理助手：hotel 库物理 17 表 = 可查 16 + 认证 1，数据 2024-08~2027-08）

**最后更新**：2026-10-26（记忆全链路时间戳化 + 压缩结构化输出 + 压缩改用主模型 glm-5.3-flash，在线实测记忆深层链路通过；前一日 10-25：日期锚点注入 + 架构反思五项——邮件链路扁平化提速 + RAG 白名单砍除 + 语料模板化 + 收件人权限剥离 + 全面登录制；10-24：邮件收权到经理级 + 写作 agent 单档化）

近期主线（函数级细节见 docs/学习文件/06近期改动详解.md；逐条记录见下方已完成清单）：
- 记忆冷层向量化（mem/ 包）+ 延迟截断 + 双坐标分离 + 回查收敛 chat + 全链路时间戳化 + 压缩结构化输出（主模型承担）；
- RAG 拆包（builder/retriever）+ 幂等增量建库 + 语料拆分 + tags.json 显式登记；
- 账号体系重建（编号+密码 / PBKDF2 纯认证表 / 无公开注册）+ 数据重造 535 万行；
- 权限五级体系（level 随 JWT，route 唯一收口门）+ 邮件 dispatcher supervisor 化 + 草稿即校验 + system 链路直连 END；
- 打磨一轮：JWT fail-fast、改密旧 token 失效、匿名会话隔离、consumeSSE 骨架、BaseToolAgent、resolve_q 收口、route 关键词层整套删除。

（更早：2026-10-16 RAGAS 四指标落地（0.96/0.90/0.92/0.88）；2026-10-01 电商→连锁酒店整体切换 + Git 初始化；v1.5.6 compare 节点删除、chunk 600）

---

# 一、未完成（按该修的顺序）

## RAG 语料 · 引入 PDF（方案已设计，做不做待拍板）

背景：语料目前只认 `rag/*.md|*.txt`（TextLoader）。行业资料（收益管理白皮书、品牌标准手册等）多为 PDF。

- [ ] **加载**：glob 加 `*.pdf`，按后缀分派 loader——`.md/.txt` 走 TextLoader，`.pdf` 走 `PyPDFLoader`（langchain_community，依赖 `pypdf`，requirements.txt 需加）。
- [ ] **切块**：PyPDFLoader 按页出 Document，先合并全文再走现有 MarkdownTextSplitter(600/120)；页码不进 chunk（key 按文本 sha1，不记页码，后续需要引用页码再加）。
- [ ] **tag**：PDF 抽出来是纯文本，整篇落文件级 tag——默认 hotel 零操作；是 business 类才 `tags.json` 加一行登记，与 txt 同一套机制。
- [ ] **manifest**：按文件 sha256 跟踪的机制不变，PDF 一样增量重建。
- [ ] **明确边界**：扫描件（图片型 PDF）抽不出文字，不做 OCR——引入时人工确认是文本型 PDF 再丢进 rag_corpus/。
- [ ] **验证**：test_rag 1.5 组补一条"PDF 文件按文件名定 tag"；在线看 chunk 数与召回。

## 后端优化 · 第三批整洁 / 低优（可顺手做）

- [ ] **C5** email_material_tool SMTP 用 `with` 确保异常路径关闭连接；群发复用一个连接（曾实施后应用户要求回退，暂不做）
- [ ] **C6** route 模块级缓存 prompt + `with_structured_output`；db/chart 抽公共 q/scope 拼装
- [ ] **C7** main.py lifespan `build_graph()` 改 `asyncio.to_thread`；CORS/裸 load_dotenv 收敛
- [ ] **登录防爆破**：编号+密码错误次数限制 / IP 限流（验证码体系删除后的新课题）
- [ ] **system 分支在 glm-5.3-flash 下回归**：10-26 主模型换型后只实测了 chat 记忆链路（压缩/注入/回查）；邮件起草（写作 agent 结构化输出）未在新主模型下跑过，上线前补一轮 B5。
- 备注：中文邮件"必失败"为误报，Python 3.12 下 MIMEText 对非 ASCII 内容自动选 utf-8+base64（已实测），无需改。

### 验证方式

每批改完重跑：`D:/Anaconda3_env/envs/lang_cg/python.exe -X utf8 test/full_regress_v156.py`
（需 Docker 起 my-redis、app/main.py 在线），目标为回归全过。

---

## P3 · context 没有统一契约

> 注（2026-10-07）：下面是该问题提出时的快照，其中 compare 节点、`context_parts` 已在 v1.5.6 删除，db/chart 的 context 段数也有调整（db 现三段、chart 含图表 JSON）。**核心问题——各节点各拼各的 context、没有统一契约——仍然成立、仍未做。**

四个节点各拼各的 context 字符串：db 拼「用户问题/表结构/查询结果/数据来源」四段、
chart 拼「用户问题/表结构/图表JSON/数据来源」、compare 用 `context_parts` 列表、
rag 直接甩检索结果。

**llm 节点只能靠 prompt 猜里面有什么，加新节点就得重新发明一套拼法。**

如果要做「换行业的通用骨架」，这条迟早绕不过去；但当前只有一个领域，
改了也验证不了对不对——**建议等真做第二个领域时再抽象**。

## 高优先级（排期参考）

- [ ] AnlyzeAgent prompt 调优：按真实使用反馈再迭代
- [ ] 单元测试覆盖（核心接口 + AI 节点 + 调度链路）
- [ ] 部署文档（Docker / 服务器部署步骤）

## 中优先级（v1.4）

- [ ] **SSE 心跳帧**（2026-10-25 全面测试实测发现）：写作 agent 起草期间服务端一个字节都不发（token 按设计不透出），requests/代理层按"无字节超时"断连——当时起草 5~8 分钟，B5 两轮 confirm 都因此 Read timed out（客户端 600s 无数据）。`_sse_events` 里加周期心跳（如每 15s 一行 `: ping` 注释帧，SSE 规范内、前端天然忽略）即可根治。10-25 扁平化后起草降到约 3 分钟，600s 不再触顶，紧迫性下降，但对空闲超时更短的代理层仍是兜底
- [ ] **HITL 断点线程的并发/僵尸防护**（2026-10-25 全面测试实测发现）：① 客户端超时断开后服务端 LangGraph 图任务不取消，继续烧模型几分钟（uvicorn 关 generator 似乎没把取消传播进 astream 任务）——排查取消传播链；② /chat 的排空只看"挂着 interrupt"，看不到"图还在跑"——同线程撞上来就双图并发写同一 checkpoint（曾致 B2 system 两轮连环失败：第二轮僵尸任务 vs 第三轮新图，confirm 晚到 8s 被客户端超时切断）。可考虑 per-thread asyncio.Lock 或 409 拒绝。测试侧已先绕开（线程名带时间戳）
- [ ] ~~前端优化：聊天界面 [object Object] 渲染 bug（frame 解析问题）~~（v1.4）
- [ ] ~~前端优化：缺"分析中..."加载提示~~（**已由 2026-09-10 的 `type:status` 进度帧解决**，8 个节点各有专属文案 + 打字光标，本条作废）
- [ ] 日志系统完善（loguru 配置、日志分级、日志文件轮转）—— **2026-09-12 做过一版又撤回**：新建过 `app/core/logging_config.py`（三 sink：控制台 INFO / app.log 按天轮转留 7 天 / error.log 只收 ERROR 留 30 天），验证 8 项全过，但用户决定不要这个系统，已完整回退（删 `app/core/`、`logs/`，`main.py` 恢复原状，回归 30 OK）。**日后要做的话，注意 loguru 默认不落文件、Windows 下必须显式 `encoding="utf-8"`**
- [ ] 性能优化（慢查询监控、缓存命中率统计）
- [ ] SystemAgent 调度链路可观测性：SSE 流式返回"调了哪个智能体/发了什么邮件"中间帧

## 低优先级

- [ ] 更多数据源支持（PostgreSQL、MongoDB）
- [ ] 多用户权限管理（角色、数据隔离）
- [ ] 知识库管理界面（文档上传、分块预览、向量检索测试）

---

# 二、已完成

## 已完成清单

> 每条只留一行记录，不再展开——2026-10 改动的问题背景 / 取舍 / 函数级细节见
> docs/学习文件/06近期改动详解.md；长期决策结论见 baseMem.md 决策段；更早期的过程明细见 Git 历史。

### 2026-10（现状的直接来源）

- [x] **10-26 记忆时间戳化 + 压缩结构化 + 压缩改用主模型**：① 全链路时间戳化——append_history 常规追加顺手打成 (q, a, ts) 三元组（哨兵分支顺手从 if 改 match/case），format_history/摘要块标签（■{ts}~{ts}）/冷层文本/回查展示全改【YYYY-MM-dd HH:mm】，build_history_text 首行加（现在：）锚点——轮次退居纯内部坐标（切块下标/embedding 幂等 key），「第53轮」式问法不再支持、时间化等价问法（"上周二下午"）可命中；② 压缩输出从【摘要】/【事实】文本标记解析改 `with_structured_output(CompressResult)` + 3 次重试（模型不按标记输出整块静默丢的坑消掉，`_parse_compress_output` 删除、解析层归零），facts 删「|第N轮」后缀；③ 压缩超时修复——route lite（timeout=25s）实测 50 轮压缩连续三次全超时，按用户拍板「不是专用，就是直接换」：.env 主模型 ark-code-latest→glm-5.3-flash、summarize 改用 `MyModel.get_model()`（timeout=80s），不加压缩专用实例。在线实测：灌 55 轮假历史 + 真发 2 轮，压缩 33s 一次成，mem_43 50 轮带时间戳，温层注入后模型主动提待办，回查答出邮箱并自报"今天 2026-10-26 16:56"。④ summarize 瘦身 + 记忆包注释统一：砍 Redis 退避层只留进程内字典（`_in_backoff()` 一个函数，置退避一行赋值内联；单进程部署下 Redis 挂时 checkpointer 本就活不了，双层是冗余）；删 MAX_HISTORY_SOFT_CAP 软上限监控（失败路径本就有 error/退避日志，哨戒冗余）；节点长表达式拆命名中间量（start/end/start_turn/ok/keep）；注释统一"全部在代码上方" + 模块级分区横幅、圈码改普通数字（对齐 mem/ 包风格）；history.py 补对外入口清单 + 双检锁注释 + 装配函数归位 + 分区横幅；summarize 144→109 行；test_memory 删 FakeRedis/_DeadRedis 替身改纯进程内断言（81 项过）。另：test/ 目录整理——_tmp 调试脚本归档 test/debug/、产物统一落 test/output/。
- [x] **10-25 日期锚点注入**：模型不知今天几号，裸"8月"会照库里数据最大月脑补年份（库数据超前真实日期，最新 2027-07）→ build_metric_block 首行注入【今天】`date.today()` + 换算规则（没给年份的月份/季度 = 最近已过去的那个；"最近N天/N月"以今天为终点往前推），语料第 17 条规范同口径双写；回归 B2 db 用例钉死"2026年8月"防歧义、判定排除"没查到"话术防假绿。
- [x] **10-25 架构反思一轮（五项）**：① 邮件链路扁平化——写作 agent 直挂 sql_query/describe_table 裸工具，SQLQuestionAgent 撤出邮件链路，每次取数省 2 次 LLM，起草 12~20 分钟→约 3 分钟（B5 实测）；② RAG 白名单机制整套砍除——retrieve_schema_with_whitelist/_extract_columns 删除，build_schema_block→build_metric_block 只回口径/规范（16 表全量列名字典由 sql_query docstring 常驻兜底，召回片段与之重复且可能残缺）；③ 语料模板化——表结构.txt→指标口径与查询模板.txt（T1~T14 标准查询模板库 + 16 条查询规范防慢 SQL：裸列区间、禁 DATE(列) 包裹、环比同比条件聚合一次查出）；④ _lookup_emails 权限剥离——砍到只剩"查邮箱"（sender_level 删、话术"员工"），发信门槛收口 route level≥3 一道；⑤ 全面登录制——匿名体验模式删除（guest: 命名空间/guestThreadId 全删），/chat 系端点全换 get_required_user（无 token/假 token 直拒 401），前端启动弹登录框（口径：能关框但功能全锁）。离线 90 过 / test_rag 10 过 / 在线 b6+b1~b5 29 过 0 失败。
- [x] **10-24 邮件功能收权到经理级**：system 分支权限门从「登录即可」收紧为 level≥3（与 db/chart 同档——实际业务不会让员工驱动系统邮箱发信）；写作 agent 两档合一档（删 JUNIOR 档与 `__TOOLS_DESC__` 占位符拼装）。回归 76 过 0 失败。
- [x] **10-23 账号体系 · 编号登录 + 数据重造 3 年**：物理 17 表 = 可查 16 + 认证 1（user_info 纯 PBKDF2 认证表，模型不可查）；数据 2024-08~2027-08 共 535 万行；验证码三接口删除、无公开注册；test_auth 27 / full_regress 76 过 0 失败 5 跳过。
- [x] **10-23 权限五级体系**：employee.level 随 JWT，route 唯一收口门（db/chart/system 均 ≥3——system 于 10-24 收权，越权自写 answer 直连 END）；收件人 level≤sender+1、外部邮箱 ≥3。当日先试的 is_senior 两档版同日被取代。
- [x] **10-23 邮件 dispatcher supervisor 化 + 链路大减法**：写作 agent 自主编排素材三件套，`EmailDraft` 结构化输出；草稿即校验（确认集=展示集，send 不重查）；system_send 三分支自写 answer 直连 END；自由文本时代的解析层/防呆层/死字段逐层剥掉。
- [x] **10-23 route 关键词层整套删除（179→113 行）**：纯 LLM 判断 + 权限门，全节点不查库；LLM 异常默认 chat（fail-safe）。
- [x] **10-23 打磨一轮（code-review D/R/P 组）**：JWT_SECRET fail-fast；pwd_sig 改密旧 token 401；匿名会话 guestThreadId 隔离；consumeSSE 骨架（send 204→106 / resumeMail 113→26 行）+ openStream 闭包重连修真·死锁；BaseToolAgent + invoke_with_structured_retry；resolve_q 收口；Redis 常量统一；State total=False 删伪默认值；死代码清理。
- [x] **10-19~20 记忆冷层向量化（mem/ 包）**：块提交三件套原子语义（压缩→embed_turns 幂等→全成才写 state）；history 延迟截断（硬上限 100 备份窗口）+ 双坐标分离（下标=轮次-deleted，P0 修复）；热层带全局轮次编号；温层摘要三段式；冷层回查收敛 chat 唯一责任方（关键词闸门/词面回查删除）；test_memory 79/79。
- [x] **10-19~20 RAG 拆包 + 语料治理**：rag_tool 421 行拆 builder/retriever；幂等增量建库（确定性 key + manifest 台账，未变 0 次 embedding）；语料一文件一主题 + tags.json 显式登记（章节标题覆盖翻车 33 段错挂后退役）；test_rag 离线 6 项。
- [x] **10-19 clarify 反问升级**：固定模板 → 轻量模型 `ClarifyGuess`（反问 + 编号候选），回序号由入口改写还原；无关键词触发 / 无 state 字段 / 无前端按钮。
- [x] **10-16 RAGAS 四指标落地**：0.96/0.90/0.92/0.88；选表指引段误召回是 precision 主失分点。
- [x] **10-01~02 业务切换连锁酒店 + 测试全量酒店化**：hotel 库 17 表/10 店种子；prompt/RAG/前端/回归脚本口径全切换；HITL 真发 1 封闭环；Git 初始化（root 589e68b）。

### 2026-09（电商版演进，多数形态已被后续重构覆盖）

- [x] **09-30 三层记忆初版（M1–M5）**：memory_facts + 分块封存 + recall_history；默认时间口径删常量/字段、只落 SQL/ECharts 两个 agent 的 prompt；history 只记原始 question（rewritten_q 不入历史）；测试目录按功能拆七个 + CLAUDE.md 并入 baseMem。
- [x] **09-28 v1.5.6 七处决策一次做完**：compare 节点删除（对比统一走 chart，10 节点）、markdown_report_tool 删除（5→4 Tool）、RAG tag 4→2 类、chunk_size 300→600、route 兜底词补全、has_time/is_topn 误判优化、知识库 286→604 行。
- [x] **09-16 standalone_question → rewritten_q 改名**（波及 10 处）+ 顺手修 writer 节点漏吃改写（六节点统一 `state.get("rewritten_q") or question`）；route 缺时间判定改查 rewritten_q（模型免费做的语义提取要用上）。
- [x] **09-15 注释全量年审**（47 个 .py 逐个 Read）+ 抓回 1 个丢失功能（auth 发码限流在重写事故中丢失补回）——教训：排查用户手改的文件只能用 Read，不能信 Grep/终端。
- [x] **09-15 名实对齐三件**：llm 节点改名 writer（token 白名单同步改，漏改流式直接哑）、route 分支改名 llm→chat（分支名与节点名一一对应）、route prompt 补 clarify 分支（僵尸分支激活）。
- [x] **09-15 ECharts 本地化**（本地优先 + 三 CDN 兜底）+ **Checkpointer 启用 AsyncRedisSaver**（同步 RedisSaver 不实现异步方法是当初禁用真因；对话记忆重启不丢）。
- [x] **09-14 auth 领域收拢成包**（api/auth/ = jwt + auth_router）+ 重写事故记录（凭记忆重写错 4 处——整文件 Write 前 Read 必须新鲜）；注释两轮清理：版本流水 159 处→0、why 叙述改功能讲解 + 每函数一行说明。
- [x] **09-13 冗余清理三轮（AST 扫描 + 函数级 grep 交叉取证）**：删零调用 @tool 包装/孤儿文件/无护栏 mysql_tool/死参数字段；第三轮只挖出 1 个死文件=边际收益递减信号。
- [x] **09-13 HITL 邮件确认**：interrupt 挂起等用户点「确定发送」（恢复后节点从头重跑 → draft/send 必须拆两节点、草稿经 state 跨断点）；新增 confirm 帧 + /chat/resume + 自动取消排空。
- [x] **09-13 拆 chat 节点**：报告写手与对话写手分离（一份 prompt 不装两种人格）；是最小提示词不是没提示词（零约束模型会瞎编）；追问从 ReAct 多轮变单次调用。
- [x] **09-13 writer 格式「严格三段式」→「用户意图优先」**：三段式只是开放式数据问题的默认值，指向明确的追问问什么答什么。
- [x] **09-13 修 rerank 从未真正工作**：wrapper 把模型名锁死 v1 且吞 403 → 直调 dashscope SDK（gte-rerank-v2）；教训：静默降级必须用日志监控兜底。
- [x] **09-11 删 sql_trace 整条假链路**（节点层拿不到 Agent 内部 SQL）+ clarify 硬编码词表 100% 误拦改「缺时间补默认口径」（此形态后续又被纯 LLM 路由取代）。
- [x] **09-12 回答体验与一致性修 5 项**：删「数据来源」段（用户要结论不要执行细节）；status 提示改说「下一步在等什么」；`_ensure_limit` 强制 LIMIT 100 硬兜底（prompt 是软约束）；删 error_count 死字段 + db 节点缓存/重试补齐（10.63s→0.00s；`_run_sql` 吞异常是有意的，retry 只管网络层）；卡片数字标【权威计算·禁止重算】治卡片与正文打架；compare 解析结构化优先（宁不出卡片，不产出规整的错数）。
- [x] **09-12 前端体验两批**：设计令牌 `:root` var() 化（157 处引用）+ 品牌去内部代号；暗色模式、进度步骤条、思考三点动画、停止生成、图表下载 PNG/柱线切换；index.html 1426→110 行拆分 html/css/js（`?v=` cache buster）。
- [x] **09-12 多轮上下文丢失终版 = 入口改写（query rewriting）**：Route 同一次调用输出分支 + rewritten_q（额外延迟≈0），下游零感知、历史只记原文；顺带 summary_upto（每 3 轮重压）+ build_history_text（compressed_summary 有了消费方）。
- [x] **09-12 行业标准流程审查修 4**：RAG 检索顺序 bug（先替换 rewritten_q 再检索）；build.py import 副作用挪进 build_graph；缓存 key 去 history（多轮可命中）；system 格式化挪回 system 节点（谁产出谁格式化）。
- [x] **09-12 二次审查修 4**：summarize 换轻量模型；AnlyzeAgent 摘查库工具（工具权限=越权能力，只留 data_calc_tool）；history reducer 改 trim 20 轮；rerank 补三段式最后一环。
- [x] **09-12 三轮审查（API/安全/数据层）+ 补真 JWT**：最大发现=文档写「JWT ✅ 已完成」实际零实现（找不到证据的"完成"比"没做"更危险）——补 HS256 + 两级校验真实现；登录 4 小安全点（发码限流/焚毁验证码/secrets 随机/user_name 前缀）。
- [x] **09-10 重复代码收敛 5 项 + 回归基线**：DB 游标三函数（query_all/query_one/execute_write）、前端 postJson/withBtnLoading、format_history 抽公共；regress_refactor 30 项基线（TestClient 不启 Uvicorn）+ 真出图 4/4。
- [x] **09-10 性能四连**：路由换轻量模型 `doubao-seed-2.0-lite`（with_structured_output 133s→3.2s）；主模型 timeout/max_retries 收紧；stream_mode 改 updates+messages 边跑边推 + status 进度帧；`get_route_model()` 独立单例。
- [x] **09-11 RAG 混合检索**：纯向量 k=3 → 向量+BM25 双路 → RRF 取 5（表名列名是专有名词只有字面没有语义）；8 题召回率 81%→100%，对外签名零变更。
- [x] **09-11 修坑三件**：pymysql `%` 占位符坑（params 为空不传第二参）；summarize 改入口条件边（不再每轮必进空转）；data_calc_tool 算子 9→3 + AnlyzeAgent 往返压缩（57.4s→25s，主模型算术实测 8/8 可信，瓶颈是轮次不是工具粒度）。
- [x] **09-11 修「假流式」**：`subgraphs=True`——create_agent 是嵌套子图，不开不转发子图 token；text 帧 1→565。

### v1.0 ~ v1.3 电商版骨架（明细见 Git 历史）

- [x] **v1.0 基础（09-01~05）**：FastAPI 服务、LangGraph 多智能体图、RAG 管线、NL2SQL、SSE 流式、前端单页、邮箱验证码登录、项目文档体系。
- [x] **秋招升级包**：data_calc_tool、markdown_report_tool、compare 节点、clarify 节点、路由 4→6 分支、MySQL 连接池、SSE 帧 2→5 种、sql_trace——其中多件后续已删除或演进（compare/sql_trace/markdown_report 均下线）。
- [x] **v1.3 砍范围 + 表结构复杂化**（customer/orders/products 加字段、4 张新表、数据库三脚本幂等）。
- [x] **v1.3 SystemAgent 定位 = 发邮件调度器**（Agent-as-Tool 调 sql/anlyze）+ notification_record 留痕 + route 加 system 分支 + 端到端真发验证。
- [x] **v1.3 阶段 3 架构整理**：节点物理平级（graph/nodes.py 拆 9 文件）+ RAG 工具化进 tool/ + 建库从 import 副作用改启动期显式调。
- [x] **v1.3 阶段 4-5 前端与验收**：推荐问题 11 个、版本号自动 reload、健康检测重连、e2e 10/10 + 出图 4/4。
- [x] **优化观塑形**：撤回 7 个"假优化"（用户原话「优化不能瞎提」）；真优化 3 项（anlyze 4 段式、连接池调优、context 数据来源摘要）。

---

## 设计得好的地方（2026-09-11 全量复审确认，2026-10-24 按现状复核）

| 设计 | 好在哪 |
|---|---|
| `clarify` 直连 END | 反问不查库。不汇入 writer 的分支各自收口，是对的 |
| rag/db/chart 汇入 writer | 取数与表达分离，换数据源不影响输出文风（system/chat/clarify 均直连 END） |
| `history: Annotated[list, append_history]` | Reducer 累加不覆盖 + 哨兵截断，语义清晰 |
| route 用轻量模型 | 分类任务不该用主模型，133s → 3.2s |
| 草稿即校验（确认集=展示集） | 所见即所发；send 不重查，每封邮件少一轮 LLM 调用 |

---

## 里程碑

| 里程碑 | 目标日期 | 状态 |
|:--|:--|:--|
| v1.0 基础功能完成 | 2026-09-01 | ✅ 已完成 |
| v1.1 测试 + 部署文档 | 2026-09-05 | ✅ 已完成 |
| v1.2 环境调通 + 架构整理 + 工具测试 | 2026-09-06 | ✅ 已完成 |
| v1.3 阶段 1：必修 1 + 数据库三脚本 | 2026-09-07 | ✅ 已完成 |
| v1.3 阶段 2：SystemAgent 重构 + 端到端测试 | 2026-09-07 | ✅ 已完成（含真发邮件验证） |
| v1.3 阶段 3：物理平级 + RAG 工具化 + 建库显式化 | 2026-09-07 | ✅ 已完成 |
| 连锁酒店管理助手（hotel 库 17 表 + 全链路酒店化） | 2026-10-01 | ✅ 已完成（上线验证通过；test/ 回归脚本酒店化 2026-10-02 完成并验证） |
| 记忆冷层向量化（mem/ 包）+ RAG 拆包与语料 tags.json | 2026-10-20 | ✅ 已完成 |
| 账号体系（编号登录）+ 数据重造 3 年 + 权限五级体系 + 邮件 supervisor 化 + 打磨一轮 | 2026-10-23 | ✅ 已完成（回归 76 过 0 失败；在线实测项待 Redis 补跑） |
| v1.4 前端优化 + 性能 | 待定 | ⚪ 未开始 |
| v2.x 数据隔离 / 多租户 | 待定 | ⚪ 未开始 |
