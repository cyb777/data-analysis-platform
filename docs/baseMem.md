# 项目开发记忆

> **本文档只装两样东西：协作约定 + 关键决策的结论。**
>
> 不装的：改动流水账、诊断过程、对照实验数据、验证结果。
> 那些是一次性的——改完验证过就没价值了，留着只会让文档越滚越长。
> （2026-09-11 用户原话：「你这个文档是不是太重复了，好多都是你改过的，
> 那些改动的记录不应该进入这种 base info 里面？而且每个文档让它做自己的功能就好了」
> 清理前本文档 775 行，其中 7 段「已归档」复盘占 600+ 行，且与 devPlan.md 内容重复。）
>
> **想看项目现在长什么样** → `baseInfo.md`
> **想看还有什么没做** → `devPlan.md`
> **想看面试怎么讲** → `项目面试八股.md`

---

## 一、协作约定（长期有效，每次动手前先看这里）

### 1. 临时测试脚本一律放 `test/tmp/`，禁止建在项目根目录

**用户原话（2026-09-11）**：「以后测试的话测试放在测试的文件里面，你别建在外面，
你看你外面建些啥？搞得整个项目结构都很乱」

坏习惯：验证时在根目录建 `_vf_xxx.py` / `_diag_xxx.py` / `_xxx.txt`。
虽然每轮结束都清理了，但**过程中用户在 IDE 侧边栏里全看得见**。
清不清是一回事，建的时候就不该建在那儿。

| 用途 | 位置 |
|---|---|
| 一次性验证/诊断脚本、输出 txt/log | **`test/tmp/`**（用完即删） |
| 沉淀下来的回归脚本 | `test/`（如 `full_regress_v156.py`、`e2e_test.py`、`test_auth.py`/`test_db.py` 等） |

**根目录只允许放**：`.env`、`requirements.txt`、`Code_Wiki.md` + 既有目录。
新增任何文件到根目录前，先问用户。

### 2. 写测试断言前，必须先读被断言对象的真实结构

同类错误犯过四次：编造不存在的表名（`product`/`order_item`）、
字段名写成 `x_data`（真实是 `x_axis`）、SQL 里写不存在的列（`order_no`/`created_at`）、
断言 `compare_result` 里有 `ratio` key（实际只进 `context`）。

**动手前先 `SHOW COLUMNS` 或先 Read 源码确认结构，一次都不能省。**

### 3. 断言要锚定可执行代码，不能用宽泛子串

踩过两次：断言「route.py 已去掉 with_structured_output」时命中的是中文注释；
断言 `.echart` 时命中的是无关字符串。

### 4. 四个文档各司其职，不要互相抄

| 文档 | 唯一职责 | 判断标准 |
|---|---|---|
| `baseInfo.md` | 项目**现在**长什么样 | 只写当前状态，不写「从 X 改成 Y」 |
| `devPlan.md` | **还有什么没做** | **未完成写在最上面**；做完就移走，不留复盘 |
| `baseMem.md` | 踩过的坑 + 定过的规矩 | 只写「下次还会用到」的**结论** |
| `项目面试八股.md` | 面试怎么讲 | 量化数据、4 段式话术都归这里 |

**「已归档复盘」这个概念本身已取消。** 一次改动做完，只有三种去处：
变成 baseInfo 的「现状」、变成 baseMem 的一行「决策结论」、或者直接删。
不保留完整过程。

**面试向文档分两份，别合并：**
| 文档 | 唯一职责 |
|---|---|
| `实习生基础八股.md` | 通用**基础八股**：Redis / MySQL / Python / HTTP·FastAPI·JWT / Docker / Agent 概念，问答式、与项目解耦为主 |
| `部分代码讲解.md` | 项目**真实机制深讲**：interrupt HITL、结构化输出、RAG 三段式、缓存 key、三层记忆、Redis vs FAISS，每点「作用/为什么/代码/追问」 |
基础归基础、项目机制归项目，两边不互相抄；更新时各管各的。

### 5. 用户的硬性偏好

- **一个一个修** —— 改动之间要彼此独立可分批验证，**不是**"一个总目标拆成多轮完成"。
  紧密耦合的子改动（删 A + B 接管 A 的活）必须一次做完——拆轮会留下半新半旧的状态。
- **先不测，改完我自己起服务看** —— 这里的"不测"指**不要起 Uvicorn 跑端到端**
  （占端口、阻塞用户起服务）。可测的：静态检查（grep / Python 启语法检查 / ImportError 验证）。
  AI 自验目的是"改完确保不报 ImportError / SyntaxError"，**不是替代用户起服务**。
- **一定要保证原来的功能没有问题，再优化** —— "保证原功能没问题"是**顺序**（先稳后优），
  不是**幅度**（优化要小）。真优化该做就做，别因为"怕动太多"而漏掉该做的改动。
- 代码注释用**中文**
- **极度反感兜圈子** —— 直接给方案，不要反复确认
- **优化必须有硬数据** —— "硬数据"是**反对虚假量化**（"提速 30%"没实测），
  **不是**"没数据就连建议都不提"。老板原话「撤回 7 个再找 5 个真优化」——
  "撤7"指虚假优化，"找5"才是真优化方向，**有就提**。

### 6. 代码注释规则（2026-09-14 用户拍板）

- **每个函数保一行功能说明**（docstring 第一行算数，缺的补上）
- 注释只写**功能讲解**：做什么、怎么用；块级为主，行级按需（详细解释时可连续用）
- **"不写为什么"有边界**：**设计意图/权衡归 devPlan/baseMem**（为什么 memory_facts 同 key 覆盖、为什么 metadata tag），
  **不指**实现陷阱（pymysql % 占位符、SDK 不抛异常、interrupt 节点重跑）——**这些必须写注释**，
  不写下一个改代码的人会重蹈覆辙。下面"实现陷阱"那批例子就是这个口径
- 用户有 langchain/langgraph 基础：基础概念不教；超出基础的机制可注
  （interrupt 恢复后节点重跑、SDK 不抛异常、pymysql % 占位符、updates 事件跑完才发这类）
- **禁止版本流水**：日期戳、`vX.Y 阶段N`、任务编号、「新增/改成/已删」叙述——
  归宿是 devPlan 已完成清单，不是代码
- 前端（app.js / style.css / index.html）不适用此规则
- 已全量清理两轮（版本流水 159 处 → 0；why 叙述 → 功能讲解），新写注释按此标准

### 7. 函数返回值用变量名替代直接返回表达式（2026-09-19 用户拍板）

**好写法**——函数内组装好变量，最后 `return 变量`：

```python
def foo():
    results = [x for x in range(10) if x > 5]
    return results
```

**坏写法**——`return` 后直接堆表达式：

```python
def foo():
    return [x for x in range(10) if x > 5]
```

**命名约定**：变量名按"它是什么"命名（如 `bm25_docs` / `reranked_docs`），
调用方再按上下文起接收名（如 `bm_docs` / `reranked`）。

**反例**：`_bm25_ranked` 之前 `return [Document(...) for i in order]`，现在改成：

```python
bm25_docs = [Document(page_content=_bm25_chunks[i]) for i in order]   # 组装
return bm25_docs                                                       # 返回
```

为什么：阅读时一眼能看到"这个函数返回什么"，不必拆表达式；
debugger 单步走也能直接看到变量值，不用 print 临时变量。

**边界**：简单变量、字面量、单纯函数调用（如 `return retrieve_schema(question)`）不堆表达式，**不用改**。
规则只针对**列表推导式 / 字典推导式 / 长字符串拼接** 这类一眼看不出的复合表达式。

### 8. 积极但不冗余（2026-09-28 用户拍板）

"不要冗余、不要加什么"和"积极做完"是两个独立维度，前者是底线，后者是节奏：

- **底线**：**不加新 Tool / 新 Agent / 新节点**（Tool/Agent/节点数 = 固定）
- **节奏**：合并 / 重构 / 迁移一次到位，**不拆轮**
- **判定标准**：该改动属于"已有 Tool/Agent/节点的接口增量"（output_type、字段、参数）→ **该加就加**；
  该改动属于"造新 Tool/Agent/节点" → **不加**
- **正例（历史，后已再演进）**：db 节点合并 compare 能力 = "Tool 接口增量 + 目标节点加分支" → 一次做完
  （删 compare.py + 改路由 + db.py 加对比分支 + markdown_report_tool 加 comparison_card + db.py 调用它，5 件套一气呵成）
  注：这是当时的重构案例；后续 v1.5.6 又彻底删除 compare 能力，对比统一走 chart 出图，db 只写 `context`。原则（一次到位不拆轮）仍成立。
- **反例（保守过头）**：删 compare.py + 改路由 → 但 db.py 不加对比分支 → 对比场景派 db 出不了卡片 → 半新半旧
- **再反例**：加 `compare_agent` 新智能体 = "造新 Agent" → 不加

### 9. AI 文档自维护协议（原独立的 CLAUDE.md 已并入本条）

CLAUDE.md 与本文档高度重复，2026-09-30 取消独立文件，独有规则收在这里。

- **改完代码立即更新文档**：完成任何实质改动（建/改/删文件、改配置、改 prompt）后，
  当场按上面第 4 条的文档分工落文档，不等提醒、不攒着。
- **每次会话开始必读**：`baseMem.md`（约定/决策）→ `devPlan.md`（还有什么没做）
  → `baseInfo.md`（项目结构），避免重复劳动、对齐用户偏好。
- **回复前自查**：刚改了哪些文件？要不要立刻更新 baseInfo / baseMem / devPlan？
  有没有避免兜圈子、直接给方案？

---

## 二、关键技术决策（结论，不写过程）

### 架构与职责

- **业务员工与登录账号分离（2026-10-23 定稿）**：`employee` 是酒店业务员工（岗位/人效/权限 level/收信邮箱，主键即员工编号=入职年4+区域码2+部门码2+序号2），`user_info` 重建为**纯认证表**（employee_id + PBKDF2 哈希），**从 sql_query_tool 撤出、模型不知道有这张表**（可查 16 张）——密码哈希物理上不在 LLM 可查面。登录 = 员工编号+密码（JOIN employee 带 level/职位/姓名，离职拒登，错误提示不区分编号/密码防枚举）；收件人查 employee（`position=%s OR employee_name=%s` 一条 OR 查询）；**无公开注册**，验证码三接口整体删除，账号随员工预置（初始 123456，改密走 change_password）。
- **预订与入住分离**：`reservation` 记录预订（可能取消/NoShow），`stay_record` 记录实际入住；OCC/ADR/RevPAR/间夜量一律以 `stay_record` 为准。各类收款（房费/餐饮/增值）统一进 `payment`（biz_type+biz_id 关联单据），营收只统计 `pay_status='已支付'`。
- **Agent prompt 不硬编码选表规则**：选表/选字段的唯一依据是运行时检索到的【表结构资料】和 `DESCRIBE`/`SHOW` 能力；SQL/ECharts/Email dispatcher 的 prompt 只保留通用 SQL 规范（聚合、GROUP BY、LIMIT、默认最近 30 天），不写死「某指标必查某表」「只能查某表」这类口径。
- **权限五级制 + route 唯一收口（2026-10-23；10-24 收权）**：`employee.level`（1实习/见习 2正式 3经理 4老板 5管理员）随 JWT 签发，/chat 每轮刷新写 `state.user_level`（代价=级别调整重新登录生效）；route 是全项目唯一权限门（db/chart/system 均要 ≥3 经理级，越权自写 answer 直连 END；匿名 user_level=0 天然被拦），**不下放节点**——下放=规则散三处、新分支漏门即越权洞。10-24 收权：发信不再"登录即可"，实际业务不会让员工驱动系统邮箱；写作 agent 随之单档化（全量三件套，删两档设计）。收件人侧规则不变：系统内 `level<=sender+1`，外部邮箱仅 level≥3。
- **邮件 dispatcher supervisor 化（2026-10-23）**：编排器预判素材源、正则抠收件人全部拆除——写作 agent（`create_agent` + 素材三件套工具）自主决定调谁调几次；成稿挂 `response_format=EmailDraft` 结构化输出（三行契约、`_WRAPPER_RE` 等自由文本时代解析层整层删除）。**草稿即校验**：起草时一次查全收件人（确认集=展示集，send 不重查）——确认时才校验会"所见非所发"。**system_send 三分支（确认/取消/失败）自写 answer 直连 END**：发送结果是模板人话，过 writer 只是同义复述还白烧一次调用。拦截话术只讲三事实：不是员工 / 没有邮箱 / 没有权限（不解释规则、权限细则不外露）。
- **安全三条（2026-10-23）**：① JWT_SECRET fail-fast——默认值启动即抛 RuntimeError，main.py lifespan 先炸再建图，不白跑 RAG 建库；② 改密旧 token 自动失效——token 带 `pwd_sig=sha256(password_hash)[:16]`，验签查库比对现值，失配/用户被删 → 401，零吊销组件（无 pwd_sig 的测试 token 跳过库比对、7 天自然过期）；③ 匿名会话隔离——前端 `guestThreadId()`（sessionStorage 存 `"g"+UUID`），同 tab 刷新稳定、新 tab 新会话。
- **Agent 基建统一（2026-10-23）**：四 agent 骨架收敛 `BaseToolAgent`（registry.py，子类只声明 tools/system_prompt/response_format 三样类属性）；结构化调用统一 `invoke_with_structured_retry`（缺结构/异常都重试 3 次，echarts 与 email_dispatcher 失败语义对齐——邮件起草失败从异常冒泡变为同款重试）；六节点 `rewritten_q or question` 样板收口 `resolve_q(state)`。
- **State `total=False` 无伪默认值（2026-10-23）**：TypedDict 类属性 `=0`/`=[]` 不产生运行时默认，纯误导读者以为字段必有值——删光后节点漏装配字段 KeyError 直接暴露，而不是读到人造 0/空表继续算错。
- **智能体职责不交叉**：SQLQuestionAgent = 只查、AnlyzeAgent = 只算+写、
  EchartsAgent = 只查+出图。**不给 AnlyzeAgent 加 SQL 工具**
  （用户原话：「设计的就是 sql 智能体分隔开」）
  → 2026-09-12 再次落实：秋招时给它加过 sql_query/describe_table「兜底」，
  结果它能绕过节点流程自己查库（口径失控 + 卡片正文数字打架的根因之一）。
  已摘到只剩 data_calc_tool。**工具权限 = 越权能力；writer 不给查库工具。**
- **AnlyzeAgent 计算口径（2026-10-19）**：求和/平均/最值/计数/排序心算（工具无此算子），
  **增长率/占比/CAGR 调 data_calc_tool**——这三类 LLM 心算易错，工具本就备了
  growth_rate/ratio/compound_growth_rate 三个算子。当日曾收窄为「仅 CAGR 调工具」
  又恢复原文，最终定在 prompt 工作流程第 2 条一句话，与工具介绍对齐。
- **入口改写（query rewriting）**：多轮上下文还原在入口做一次——route 同一次
  轻量模型调用输出 `{branch, rewritten_q}`，下游 db/chart 零感知。
  **不要给每个下游节点各拼历史**（还原责任分散 ×N、token ×N）。
- **谁产出谁格式化**：writer 节点对所有上游零分支感知——system 结果的格式化
  写在 system 节点里，不泄漏到 writer 节点。新增第七个分支时 writer 不该加 if。
- **writer 的固定格式是默认值不是枷锁**：三段式只约束「开放式数据问题」，
  指向明确的追问（"具体怎么做"）问什么答什么。**给 LLM 的格式要求必须
  回答"什么时候可以不用"**，否则它会在所有场景硬套——包括不该套的场景。
- **一份 prompt 不装两种人格**：writer 节点原来既做取数汇总（报告写手）又接
  对话式追问（聊天），格式要求互相拖累。拆出 chat 节点（最小提示词、单次
  调用、无工具）接 route 直派的追问，直连 END——与 clarify 同一先例。
  **单一职责拆到节点粒度；不是「没有提示词」，是只留底线约束**
  （零约束的模型没有人设，会瞎编数据）。
- **审查节点流程要查「流量纯度」**：不只问「每个节点是否完成声称的职责」，
  还要问「一个节点是否混了两种职责不同的流量」——writer 节点的双人格问题
  前三轮审查都漏了，就是只查了前者。这类问题静态审查看不出，
  靠真实多轮行为追踪才显形（同缓存多轮不命中）。
- **有副作用的动作必须有人工断点（HITL）**：发邮件前 interrupt 挂起等用户
  点确定，确认后才真发。两个 LangGraph 机制要点：**interrupt 恢复后节点
  从头重跑**——所以「起草」和「断点+发送」必须拆成两个节点（draft/send），
  草稿经 checkpointer 的 state 跨断点传递，否则起草的 LLM 调用会白跑两遍；
  **取消路径自写 answer 直连 END**，不走 writer 润色（确定话术不给 LLM 改写，
  还省一次往返）。恢复接口不接受客户端再报身份，user_id 以断点时刻
  checkpointer 里存的为准。
- **隐性契约：进 writer 漏斗的节点必须写 context**。context 是无 reducer 的
  普通字段，checkpointer 会让上一轮的值残留——chat 靠它拿上一轮数据是
  feature，但漏斗节点漏写就会把旧数据混进无关的新回答。
  已验证 4 个漏斗节点（rag/db/chart/system）全部无条件写入，
  失败路径也写。新增漏斗节点时这条必须守住。
- **共享组件不为单个调用方改**：单例 Agent / 全局 prompt 的差异化要求放调用方一侧
  （早期 compare 的 `_JSON_HINT` 只附在自己那路的 question 后面——compare 现已删；
  权威数字标【禁止重算·必须原样引用】进 context），db/chart/rag 等其他分支零感知。
- **架构缺陷不靠调用方打补丁**：clarify 误拦曾靠前端假后缀遮羞，只对推荐问题
  有效、手打问题照样被拦；正解是修 route 本身（缺时间补默认口径，不再关键词改判）。
- **图管编排，智能体管干活** —— 记忆由图的 checkpointer 管，Agent 内部不设 memory
- **模块顶层不做副作用**：`build_vector_store()` 放模块顶层 = import 即触发
  embedding 调用 + Redis 连接（单测 import 任何模块都花这笔钱）。挪进 lifespan。
- **schema 集中在 `app/ai/schemas/`**，前缀 `llm_` = LLM 输出形状 / `tool_` = 工具入参。
  **不再拆成两个目录**（拆过一次，用户反馈「跳来跳去更乱」）
- **节点物理平级**：`app/ai/nodes/` 与 `app/ai/graph/` 同级
- **分支名与节点名一一对应**：route 的分支词（chat）和承接节点（chat 节点）、
  节点职责（纯写手）和节点名（writer）必须同名同义——名字对不上时，
  读代码的人会以为那是死代码或猜错职责（llm→writer 改名的动因）。
- **默认时间口径只写在 SQL/ECharts 两个 agent 的 system prompt**：规则为
  「没指定时间默认最近30天并注明；问题已含时间以问题为准；TOP N/最高最低按全时段排名」。
  无常量、无 state 字段、无节点拼接、无入口传值。早期的 `DEFAULT_TIME_SCOPE` 常量和
  `default_scope` 字段是纯透传中转（TypedDict 字段 `=0` 也不是运行时默认值），已彻底删除。
  规则的唯一事实来源就是干活智能体自己的 prompt。
- **history 只存用户原始 question，rewritten_q 绝不进历史**：所有写历史的出口
  （writer/chat/clarify/system_send 取消分支）统一记 `state["question"]` 原文。
  改写后的自包含问题只在本轮下游取数用，不入冷层——避免多轮改写叠加导致语义漂移，
  也让 history 永远是用户视角的事实原件。
- **RAG 拆包：builder 管建、retriever 管查（2026-10-19）**：旧 `app/ai/tool/rag_tool.py`
  建库/检索混居 438 行，拆为 `app/ai/rag/builder.py`（根目录 rag_corpus/ 多文档 → 分块打 tag →
  幂等增量入库 + BM25）与 `app/ai/rag/retriever.py`（双路召回/RRF/rerank）。
  同时删 `retrieve_schema_rag_tool`（@tool 包装）与 `RAGSchema`——rag 节点是图编排内
  普通函数不是 agent，直调 `retrieve_schema(tag="hotel")` 即可，@tool 包装是早期
  「rag 节点是 LangChain agent」误解留下的死代码。
- **确定性动作不挂 @tool，发信时机由图编排定死**：发邮件是确定性动作，
  `send_email_direct` 不收进 LLM 工具链——system_draft 起草 → interrupt 人确认 →
  system_send 才真发，模型只负责起草内容、摸不到发送键。邮件代码一个文件装下
  （`tool/email_material_tool.py` = 素材三件套 @tool + SMTP 直发/留痕；早期 service/ 层已撤销并入）。
- **反问要"给候选"而不是只反问（2026-10-19）**：clarify 从固定模板升级为
  「猜意图 + 编号候选」。三条理由：① 用户被反问时常常"知道不对但说不出对的是什么"，
  只反问等于把澄清成本全推给用户；② 候选问题由 LLM 结合历史猜（换门店/时间/指标/对比/图表），
  用户回个序号就能走对路；③ "也可以直接补充"兜底，避免候选框死用户。
  **候选走 answer 纯文本，不下发结构化、不做前端按钮**：编号候选拼进 answer
  随对话进历史，用户回"1"由 route 入口改写还原成完整问题——"选择"这个动作
  也沉淀进对话流，多轮上下文连贯；曾做过 `clarify_result` 字段 + 可点按钮
  （点击即发），同日拆除：按钮绕开对话流，还白占一个 state 信道。
  **LLM 失败兜底只要反问句、不要通用候选（2026-10-20）**：删 `_FALLBACK_OPTIONS`——
  LLM 都猜不出意图时，甩三个通用候选是假装会猜、几乎不命中还误导；兜底只留一句
  平实反问（`_FALLBACK_TIP`），保证请求不炸即可。
  **`need_clarify` 字段删除（2026-10-20）**：它与 `route=="clarify"` 信息同源，属冗余——
  route 不再写入，chat_router 改判 `values.get("route") == "clarify"`，State 字段数不变
  （同日新增 `history_deleted`，一删一增仍 14 个）。
  **触发面**：除原有"太模糊"，新增"用户对上一轮回答不满/否定"——交给 route
  的 LLM 语义判断（prompt 写死两类场景），**不加关键词拦截**。曾试过
  `_is_dissatisfied` 关键词短路，"不是"太宽得叠"有历史 + 短句"两道闸才不误伤
  （"是不是"里就含"不是"），同日删除：轻量模型语义判断足够稳，不留硬编码。
  **不新增图节点、不进 registry**：clarify 无工具、单次结构化调用，与 route 同范式；
  为它单开 `agent/` 类 + 注册中心是过度设计（对照「分支名与节点名一一对应」）。

### 模型与性能

- **路由用轻量模型** `doubao-seed-2.0-lite`，不用主模型。
  主模型 `ark-code-latest` 走 `with_structured_output` 实测 133s（超时重试），换后 1.5~2.9s。
  **分类任务不该用主模型。**
- **route 纯 LLM 判断，不加关键词层（2026-10-23 定稿）**：关键词拦截/纠偏/兜底
  （含 v1.5.6 那套词表与动态职位词表）整套删除，route.py 179→113 行、全节点不查库。
  教训：豁免名单是打地鼠永远补不全——关键词层把 LLM 判对的题改错
  （"邮件里写了什么"被纠成起草邮件），比它防的"判丢发信意图"更常见；
  LLM 异常走顶层默认 chat——无工具、不取数不发信，是 fail-safe 降级方向。
- **`subgraphs=True` 是流式的充分条件**。`create_agent` 生成的 Agent 是嵌套子图，
  LangGraph 默认不转发子图 messages 事件，不开这个参数就是「假流式」。
  config 透传非必需（langgraph 1.0.4 行为，与早期版本记录不同）。
- **LLM 会并行发 tool_call**，瓶颈是**轮次本身**不是工具粒度。
  减少工具数量、放宽「必须调工具」的约束，比让工具支持批量有效得多。
- **当前主模型算术可靠**：实测 8 题（五位数除法、负增长率、五数求和）8/8 全对。
  老注释里「LLM 算术错误率 35%」是过时结论，不要再拿它当设计依据。

### 数据与检索

- **RAG 三段式**：召回（向量+BM25 双路）→ 融合（RRF）→ 精排（gte-rerank）。
  **名次 ≠ 相关性**——RRF 按名次融合，但同义段和字面近邻段分不清谁更贴，
  reranker 对候选池逐段打分。任一级不可用都自动降级（哲学同 BM25）。
- **RAG 单库 + metadata tag**：一份知识库按章节打 metadata tag，rag 节点按 tag 过滤召回段（业界主流：LangChain / 阿里云百炼 / Notion AI 都是这个模式——不是拆 2 份库）。
- **RAG tag 固定 2 类：business + hotel**：业务节点（db/chart/email_dispatcher）显式传 `tag_filter="business"`（表结构.txt=SQL 侧字典一本通）；rag 节点传 `tag_filter="hotel"`（业务知识通识.txt）。业务节点必须显式传 tag（不传等同召回全库，含 rag 段污染 SQL 生成风险）。
- **RAG tag 判定：tags.json 登记表（2026-10-20 定稿）**：`rag_corpus/tags.json` 记 `{文件名: tag}`，builder 查表打**文件级** tag，**没登记的文件默认 hotel**。默认归 hotel 不归 business 的考量：business 语料就表结构一本（固定，登记一次完事），业务知识会持续扩充（新增免登记）；漏登记的新文件只进 hotel（rag 多召回一段），不会反向污染 SQL。一个文件一个主题、整篇一个 tag，不做文件内章节级判定。两条隐式规则已退役：① 文件名规则（含「业务知识」→ hotel）——文件名无意中会命中；② 章节标题覆盖（`TAG_BY_SECTION`）——切分不保证章节标题落在段首，曾把整本 SQL 口径错挂成 hotel（db/chart 召不到指标口径，真回归）。教训：**显式登记 > 隐式推断**；新增语料 = 丢文件（hotel 零操作，business 才 tags.json 加一行）。语料现状 2 文件：`表结构.txt`（表范围+16 张可查表+指标口径+查询规范，SQL 侧字典，登记 business）/ `业务知识通识.txt`（业务通识 12 节，默认 hotel）。
- **切分器选 MarkdownTextSplitter**：两者底层切分逻辑一致（MarkdownTextSplitter 是 RecursiveCharacterTextSplitter 子类），选它的原因是"按章节成组"——优先按 ## 标题切，每段自动带标题 → metadata tag 识别省一步。RecursiveCharacterTextSplitter 也能识别 ## 但不会优先成组，要后处理。
- **chunk_size 选择（v1.5.6）**：BM25 算法需要足够 token 统计词频 × 文档长度，500-800 字符是经验甜点（vector 召回也完整）。300 太短 BM25 几乎没用，1500+ 太长 RRF 融合样本不够。**当前 chunk_size=600 / overlap=120**（500/800 都行，600 是中位）。
- **建库幂等与增量（2026-10-19）**：确定性 key `kb_43:{sha1(chunk)[:16]}`——同内容
  重复 add 覆盖同一 Redis hash，重启不再翻倍（旧版每次启动无脑 add_texts，
  重复段曾污染检索公平性）；manifest 台账（`rag_corpus/.manifest.json` 记
  {文件名: sha256+chunk_keys}）：未变跳过（0 次 embedding / 0 次写库）、
  变更先删旧 keys 后写、文件移除清残留；有数据无台账判定为旧版数据，
  FT.DROPINDEX DD 一次性自清重建。语料放根目录 `rag_corpus/` 支持多文档（非项目文档，迁出 docs/）；
  BM25 纯内存每次启动全量重建（无网络、耗时可忽略），不受增量跳过影响。
- **RAG 设计自评（2026-09-18 秋招面试场景）**：算法层（双路+RRF+rerank）
  + 工程坑认知（直调 SDK 不走 wrapper）≈ 80 分；架构层（rag 节点中转）
  + 反馈层（无用户反馈闭环）≈ 50 分。**面试讲好算法 + 主动说出「哪里可优化」
  反而更显真实**。可优化点：① 知识库 28 段太薄 + 通用字符分块 → 应按表切块；
  ② 缺 query expansion / HyDE（短 query 召回率上不去）；③ 缺用户反馈闭环。
- **RAG 效果量化评估体系（2026-10-16 定稿）**：两条链分开评——
  - **知识库问答链**（自然语言答案）：RAGAS 四指标，脚本 `test/test_ragas.py`（ragas==0.3.9），
    12 题自建集 + 参考答案取自知识库第四章原文，评委=主模型同款 temperature=0、embedding 与线上一致。
    结果：**faithfulness 0.96 / answer_relevancy 0.90 / context_recall 0.92 / context_precision 0.88**。
  - **SQL 取数链**：答案不是陈述句，四指标不适用，看执行准确率（早期 40 题 92%）。
  - 检索侧单点：8 题固定召回集，纯向量 81% → 三段式 100%。
  - **可复现要求**：评测脚本先 `FT.DROPINDEX kb_43 DD` 清空重建（段数随语料扩充变化：评测时为 51 段，2026-10-20 拆分+扩充后更多）。
    （2026-10-19 起线上建库已幂等——确定性 key + manifest，重启不再产生重复段；
    评测侧仍保留清空重建以锚定公平性。）
  - **评测发现 → 优化方向**：4.12「典型问题选表指引」段过长且被高频误召回（多题 top-5 占两位），
    是 context_precision 主失分点（"提升 RevPAR 手段"题 0.50，正解段被挤到第 2/4 位）
    → 知识库长章节细分 + rerank 候选池调优；context_recall 的失分形态是
    「参考答案某陈述点对应的段未进 top5」（如 RevPAR 题的间夜量段）。
- **rag 节点是否多余**：route 把「只问指标口径」路由到 rag 节点，
  rag 节点调 RAG 拿资料 → writer 转自然语言。**业界常见做法是 chat 节点
  自己调 RAG 工具，rag 节点这一层可省**——这是架构可优化项，不是 bug。
- **k 值比算法更重要**：召回率上不去时先怀疑 k 太小（k=3 → k=5 就从 81% 到 94%）
- **Embedding 用 DashScope** `qwen3.7-text-embedding`（`.env` 实际值；代码默认值为 `text-embedding-v4`，被 env 覆盖）
- **MySQL 用 DBUtils 连接池**，不在 pymysql 内部建连接
- **SQL 规范写进 prompt + 代码硬兜底**：ranking 必须 `ORDER BY` + `LIMIT`、
  多表必须 `JOIN`；`_ensure_limit` 给没写 LIMIT 的 SELECT 自动补 LIMIT 100
  （prompt 是软约束，代码是硬约束）
- **history 延迟截断（2026-10-20 定稿，取代"压完立刻截断"）**：块入库成功后原文**不立刻删**，
  留在 history 里当滚动备份；只有 `len(history) > HISTORY_HARD_LIMIT(100)` 才哨兵删最老一块
  （`("__truncate__", keep:int)`，int 守卫防误触发；keep= len(history)-len(chunk)，删除量 ≤ 新 upto，
  保证只删"已入库"的轮次）。入库失败时 upto 停走、未入库的一律不删——history 自然攒着，
  这就是失败缓冲带。早期对话内容靠冷层语义回查按需取回（不常驻 prompt）。
- **双坐标分离（2026-10-20，P0 修复）**：`summary_upto` 是**全局轮次**，延迟截断删轮次后
  列表下标与轮次永久错位——严禁拿它直接切 history。新增 `history_deleted` 字段
  （已累计哨兵删除的轮次，截断时与 upto 同步累加）：**列表下标 = 全局轮次 - history_deleted**。
  `should_compress` 的全量轮数 = `history_deleted + len(history)`；热层/切块都按
  `history[upto - deleted:]` 切。`summary_upto` 只做全局锚（块标签、事实轮次、embedding key、
  热层编号），**严禁对它做减法**——key 按 `sha1(thread:轮次)` 生成，轮次错一位就静默覆盖冷层数据。
- **三层记忆定稿（2026-09-30，取代 09-18 的 a/b 字段方案）**：
  - **热层** `history[summary_upto - history_deleted:]`（未压尾部，与有无 thread 无关同一切片口径）：长度 5↔54 周期波动，永无空窗——不能只放固定最近 5 轮，否则两次压块之间的轮次会同时掉出热层和块。history 本体是「未压尾部 + 已入库未删的备份窗口」（物理长度稳态 55↔105），注入 prompt 的只是未压尾部。注入时每轮带【YYYY-MM-dd HH:mm】时间戳（2026-10-26 时间戳化；轮次退居纯内部坐标：切块下标/幂等 key）。
  - **温层** ① `memory_facts`：压缩结构化输出的事实清单（`{key, content}` 条目，预设 key 邮箱/身份/口径/指标/收件人，**同 key 新条目覆盖**、其他追加，零额外 LLM 调用）② `compressed_summary`：50 轮一块的**结构化摘要**（【结论≤6】【硬数据≤8】【待办≤3】三段固定格式，宁多勿漏——非 chat 分支拿不到冷层原文，对早期对话的全部认知就是摘要+事实，硬数据段是跨轮数字连续性的兜底），**压一次即封存只追加**，不再全量重压。
  - **冷层** mem_43 向量索引（2026-10-19 起，原"history 全原文不截断"废止）；**冷层语义回查只在 chat 节点做**（2026-10-20 定稿）——chat 承接追问/闲聊，追问、指代、溯源类问题归它，`mem_recall(query=rewritten_q or question, 向量+rerank，跳 BM25)`；route/writer/clarify 一律只调 `node_history_text`（拼热层+温层，无回查开关）（route 判断分支不需要；writer 吃前序节点查好的当前资料，注入旧轮原文反而会让模型把旧数字当本轮数据用；clarify 猜意图靠摘要/事实足够）。故无关键词闸门、无轮次编号直取、无 jieba 词面兜底（三者均在 2026-10-19~20 删除，见下"冷层三处逻辑修正"）。
  - **已知限制（2026-10-20 列入）**：冷层不做「第N轮」精确直取——语义回查找"第53轮"三个字找不到内容。
    兜底路径：热层按【时间戳】文本定位；冷层靠语义复述命中（时间化等价问法"上周二下午"可命中）。判为极低频，不建专用通道。
  - **压缩失败走进程内退避**：模块级 `_in_backoff()` + `_backoff_local[thread_id]`（到期 monotonic；置退避是一行赋值，内联在节点里），TTL 600s，进 summarize 先查、失败置，退避期不重试；不写 state——临时熔断不污染业务快照。**演进**：早期退避键在 Redis（图多 worker 共享），10-19 加进程内字典兜底（压缩失败与 Redis 挂常是同一原因），10-26 砍 Redis 层只留进程内——单进程部署下 Redis 挂时 checkpointer 本就活不了，双层是冗余；重启即清，顶多补烧一次。
  - **组装统一入口 `build_history_text`**：有 upto 出三段【关键事实 + 历史摘要 + 未压原文（带【时间戳】）】，无 upto 直接全量原文（同样带时间戳）。梗概与事实矛盾以事实为准，事实间矛盾以后压的（更晚）为准。
  - 不变常量：`CHUNK_SIZE=50` / `KEEP_RECENT=5` / `HISTORY_HARD_LIMIT=100`（`MAX_HISTORY_SOFT_CAP=500` 软上限 10-26 删——失败路径本就有压缩 error + 退避 warning 日志，500 轮哨戒冗余）；压缩节奏按未压尾部算（尾部攒到 55 轮触发）；防 checkpointer 涨靠「延迟截断有界」（硬上限 100 删最老一块）。
- **冷层向量化 + mem/ 包（2026-10-19）**：
  - **记忆域独立成包**：`app/ai/mem/`（history=冷层向量库 / compress=压缩 / recall=组装+回查），
    原 `graph/context_compressor.py` 撤销、按职责拆入。rag/ 只管 kb（builder/retriever 各 1 处
    机械改：`make_vector_store(index_name)` 参数化、`_rerank`→`rerank` 公开）——
    "kb 语料"与"对话记忆"两种语料两个家；graph/ 回归纯编排（state/build）。
  - **块提交原子语义靠顺序+幂等收敛，不是事务**：compress → `embed_turns`
    （确定性 key `mem_43:{sha1(thread:n)}`，重压覆盖不翻倍）→ 全成才一次写 state
    （摘要/事实/upto/哨兵截断）；任一失败不写 state、置退避 600s（沿用旧失败语义）。
  - **mem tag 必须哈希化且只用安全字符**：`mem_{sha1(thread_id)[:16]}`——thread_id 是 `u3:邮箱` 形态，
    `:` `@` `.` 直接进 RediSearch TAG 查询语法会炸；入库与回查共用同一 `mem_tag()` 生成函数。
    前缀用下划线（不是 `mem:`）：查询侧 filter 是**裸拼字符串**（`@tag:{...}`），绕过 redisvl 的转义器，
    TAG 值里的标点（含 `:`）属未定义行为，`[a-z0-9_]` 才稳（2026-10-20 复查修正）。
  - **单游标**：`summary_upto` 恒等于 embedded_upto，不新增 history_offset 字段。
  - **state 零新增字段（同日自我修正）**：曾加过 `thread_id`/`mem_v2` 两个字段，当日删除——
    thread_id 是**重复存储**（`config["configurable"]["thread_id"]` 本来就有），
    改为 5 个节点（route/writer/chat/clarify/summarize）签名注入 config 拿；
    mem_v2 只是 legacy 迁移的桥接标记，用户拍板"老用户先不管"后改为
    **部署时一次性清空旧 checkpoint**（`redis-cli --scan --pattern "checkpoint*" | xargs redis-cli del`），
    之后「有 thread_id 且 upto>0 ⟹ 已截断」天然成立。**能复用现有通道就不加 state 字段。**
  - **无 thread_id 路径保留**（单测直连）：跳过 embedding 与截断，只做摘要+事实+推进 upto；
    切块必须用 `history[summary_upto:len-5]` 扣掉已压部分（2026-10-20 修复，见下条），
    回查不做（无向量库）。
- **冷层三处逻辑修正（2026-10-20）**：
  - **无 thread 路径二次压缩重压旧块（真 bug）**：`chunk = history[:len-5]` 隐含"history 已截断"
    假设，只对有 thread 的生产线程成立；无 thread 路径 history 是全量，第二次压缩会把 1~50 轮
    重压一遍还标错轮次。修法：起点改 `0 if thread_id else summary_upto`，
    再加 `len(chunk) < CHUNK_SIZE` 放行守卫（条件边 `should_compress` 按已截断语义估算，
    无 thread 路径会偏多判，不守卫会每轮误压）。生产路径行为一字不变。
  - **热层「第N轮」重复注入**：原 `recall_history` 有一分支把热层里的第 N 轮复制进【原文回查】，
    但该轮原文已在【最近对话】里（同一段文本 prompt 出现两次）；而 `upto==0` 时回查闸门不放行、
    热层又无编号，模型根本定位不了第 N 轮。修法：【最近对话】带定位坐标——10-20 是全局轮次
    编号，10-26 改【YYYY-MM-dd HH:mm】时间戳（`format_history` 输出与 mem_43 存储、压缩 prompt
    三方一致；轮次退居纯内部坐标）。
  - **回查归属与触发（当日三次定稿：关键词闸门 → 每轮无条件 → 收敛到 chat）**：先按关键词闸门
    （`need_recall` 词表）触发，当日推翻——**入口改写（`rewritten_q`）每轮都把追问变成自包含
    问题，本身就是理想的语义检索 query**，挑关键词反而漏（"它的入住率多少"这类指代无溯源词
    却必须查冷层）。中间态试过"落点节点（writer/chat/clarify）都查"，再收窄为**只在 chat 查**：
    回查独立成 `recall_text(state, config)`（有冷层 `upto>0` + 有 thread_id + 有 query 才查，
    `mem_recall(query=rewritten_q or question, top_k=2)`，命中返回【原文回查】段、否则返回空段），
    **只有 chat 调它并自行拼接**；`node_history_text` 去掉 `with_recall` 开关、回归纯拼历史
    （热层+温层，各节点都调，天然不碰向量库）；route/writer/clarify 因此只拼历史
    （route 判分支不需要冷层；writer 注入旧轮原文会让模型把旧数字当本轮资料；clarify 猜意图靠
    摘要+事实够）——回查成本只落在 chat 这一条分支。"回查"与"拼历史"的正交拆分是当日第三次
    修正：先是一个函数带开关，用户指出"回查直接单独 recall 就行，别的就是拼节点历史"。
    删除 `need_recall` / `_RETRACE_PATTERNS` / `_TURN_RE` / `mem_fetch_turn`（按编号点名的确定性直取一并删除）。
    配套：**route prompt 明确把"回溯早期对话"类问题派给 chat**（引用自己早前说过的细节、回顾
    之前聊过的内容），判据是"指代能靠 rewritten_q 还原成自包含取数问题 → 照常派 db/chart；
    不取数、只是要翻早期原文 → 派 chat"，并在对话历史行注明"较早对话已压成摘要，细节原文只有
    chat 能回查"。回查触发因此**寄生在路由分支判断上**：零额外成本、零新字段，代价是路由若把
    需翻冷层的问题判给 writer/db，该轮只能靠改写后的自包含问题 + 温层 facts 兜。
    其余取舍：① "第53轮说了什么"这类无内容词、按编号点名的问法不再支持（冷层内容 route 看不见，
    改写也无法还原）——判为极低频、可接受。② 回查段措辞改为"与当前问题无关时可忽略"。
- **宁可不出结果，不产出「很规整的错数」**：compare 曾兜底抓正文前两个数字标
  「对象1/对象2」——那可能是年份或订单号，算出的增长率看着很像真的。
  现在 COMPARE_JSON 解析失败就不出卡片。

- **`_run_sql` 吞异常是有意的，不要"修"**：`mysql_tool._run_sql` 用
  `except Exception: return f"查询失败：{e}"` 把 SQL 错误变成字符串返回。
  这意味着 **SQL 报错不会抛异常、LangGraph 的 RetryPolicy 收不到、不会重试**。
  这是对的——SQL 写错了重试 3 次还是错，白烧 3 次 LLM 往返；
  把错误文本交给 Agent，它能看着报错自己改 SQL 重写一遍。
  所以节点的 `retry_policy` 只针对**网络层瞬时故障**（`ConnectionError`/`TimeoutError`）。
- **节点缓存 TTL 按"数据变化速度"定**：rag 300s（表结构口径几乎不变）、
  chart 180s、db 60s（业务数据变得快）。
  db 缓存实测提速 10.63s → 0.00s。
- **缓存 key 必须在真实场景实测**：`CachePolicy` 默认对整个 state 哈希——
  多轮对话里 history 每轮变 → 同一问题第 2 轮问**永不命中**
  （之前「10.63s→0.00s」只是首轮 history 为空的特例）。
  自定义 `key_func` 只取「用户 ID + 改写后问题」（`f"{user_id}|{q}"`）。**首轮单问是实验室场景，
  多轮追问才是用户场景。**
- **低复杂度任务用轻量模型**：路由、历史压缩都是——主模型只干取数/分析/出图。

### 踩过的坑（会再犯的那种）

- **pymysql 的 `%` 占位符陷阱**：`cur.execute(sql, params or ())` 只要传了第二参
  （哪怕空元组）就走 `sql % args` 格式化，导致 `DATE_FORMAT(d,'%Y-%m-%d')` 里的
  `%Y` 被当占位符报错。**params 为空时不能传第二参。**
- **池化连接不开 autocommit 会读旧快照（2026-10-19 修）**：DBUtils 连接池反复复用
  同一批连接，默认 REPEATABLE READ 下连接持事务快照——别的事务已提交新数据，
  旧连接再 SELECT 还是旧值。`_conn_kwargs` 加 `autocommit=True`。
- **前端 text 帧必须累加不能覆盖**：真流式下一段回答拆成几百帧增量，
  要累积到 `acc` 再整体 `renderMd(acc)`。不能逐帧拼 HTML（Markdown 语法会被截断）。
- **前端 openSSE 必须【同步】返回 `{close}` handle，不能标 async**：
  调用方写的是 `stream = openSSE(...)` 再 `stream.close()`；一旦函数是 async，
  拿到的是 Promise，cleanup 第一行 `stream.close()` 就是 Promise.close() → TypeError，
  后面的 `state.sending=false` 永远执行不到——表现为「答完后输入框不解锁、
  必须手动点停止」（stopGenerating 靠 try/catch 吞异常才能复位）。
  正确写法：函数同步 return handle，真正的异步读取收进内部不 await 的 IIFE；
  cleanup 里对 stream 加 `if(stream)` 保护。EOF 兜底和 done 帧调同一幂等 cleanup。
- **@tool 注册名 ≠ 函数名**：`data_calc_tool` 函数注册名是 `data_calc`，写断言时别搞错
- **Windows PowerShell 默认 GBK**：emoji 必报错。
  用 `$env:PYTHONIOENCODING="utf-8"` + `-X utf8`，或输出 `[OK]`/`[NO]` ASCII 标记
- **观测数据要在产生处采集**：SQL 溯源失败就是因为想在节点层「事后补」，
  而 SQL 是 Agent 在 tool_call 内部执行的，节点层只能拿到返回值拿不到入参
- **文档与实现的一致性也是审查项**：JWT 在文档里写「✅ 已完成」实际零实现，
  登录只返回 user_id 让前端自报身份。Grep 全项目找证据——
  **找不到证据的「完成」比「没做」更危险，它让你以为安全了。**
  （2026-09-12 已补真实现：auth.py HS256 + 两级校验；当时 SSE 用 EventSource
  不能自定义 header，/chat token 走 query param——现已改用前端 fetch 手写 SSE +
  `Authorization: Bearer` 头，query param 仅作后端兜底）
- **静默降级必须用日志监控兜底**：rerank 上线后从未真正工作——降级退回 RRF
  让用户完全无感知，但日志每次都在报 NoneType。直调 SDK 才看到真实错误是
  403 AccessDenied（langchain wrapper 把模型名锁死成 v1 且吞状态码）。
  **降级保证可用性，也把 100% 失败藏住；冒烟测试必须读日志，不只点页面。**
  关键路径对第三方 wrapper 留个心眼：可能吞错误、锁参数，值得直调 SDK。
- **跑 ragas 的三个坑（2026-10-16）**：① ragas 0.3.9/0.4.3 顶层 `import ChatVertexAI`，
  而 langchain_community 0.3.31 已删该模块，import ragas 直接炸 → 在 import 前往
  `sys.modules` 注入占位类绕过（评委走 OpenAI 兼容，永不实例化它）；② 评委 LLM 不开
  streaming 时，豆包网关长 prompt 撑满 timeout 反复重试（48 任务预估 2 小时）→
  `streaming=True` + `max_workers=12` 压到约 12 分钟（与线上主模型单例开流式同理）；
  ③ 豆包不支持一次返回 3 条 completions，AnswerRelevancy 自动退化 1 条继续跑，
  该指标分数略保守。版本锁定 `ragas==0.3.9`（0.4.3 同样不兼容）。
- **astream 应用必须用 AsyncRedisSaver，不能用同步 RedisSaver**：同步版不实现
  aget_tuple/aput，base 类直接抛 NotImplementedError（2026-09-15 实证，这就是
  当初禁用 RedisSaver 的真因）。两个配套坑：AsyncRedisSaver 的**同步** get_state
  也报错（要用 aget_state）；asetup() 是协程，同步上下文 asyncio.run、
  uvicorn 事件循环内只能交给 lifespan await 补跑。
- **改文件名级别的重命名要防两处回退**：① 同文件多处编辑必须串行
  （并行 SearchReplace 互相覆盖，丢过 add_node 注册行）；② IDE 里开着的旧 buffer
  一保存就把 AI 的改动回退成半新半旧态（schema Literal 实例：描述已是新名、
  枚举还是旧名，靠 fallback 碰巧能跑）。**编辑后 grep 验证，不能信"我刚才改过"。**
- **排查用户手改的文件只能用 Read，不能信 Grep/终端**：Grep 和 RunCommand 走
  沙箱文件视图，用户在 IDE 里的改动可能延迟同步（rag_tool.py 实例：用户 6 处
  「LLM→writer」误替换，Grep 全盘扫不到，Read 才看到）。**AI 自己的修改两边
  都能看到，用户的修改只有 Read 可靠。**
- **写文件前必须先输出讲稿、等用户点头再 Write**（2026-09-18 用户多次强调
  「先输出，再写」/「我都让你改了，你别一直这样」）。讲稿要短——2000 字
  讲稿 + 自测题 + A/B/C 表格会占满屏幕，用户原话「你的总结里的记忆太费事了」。
- **不要反复确认 A/B/C 三个方案**——直接给推荐方案 + 一句「换方案告诉我」
  （baseMem L68「极度反感兜圈子」的具体执行版）。用户在 rag_tool 重排那次
  连出 3 版顺序方案（漏斗→阶段→深度）都被否，**真正能落地的"使用顺序"
  是「被调用的先写，调用它的后写」**——这一条是用户亲口教的标准。
- **rag_tool 文件组织标准（2026-09-18 用户定调）**：函数顺序按"被调用的先写"，
  模块顶部用 `# ====== 层级 ======` 分隔注释，全局状态（`_vector_store` /
  `_bm25` 等）紧跟被它服务的函数，不要散落。

---

## 三、环境配置（2026-09-15 更新）

| 项 | 配置 |
|---|---|
| LLM | 火山方舟 Coding Plan（`ark-code-latest` + `/api/coding/v3` 端点） |
| 路由模型 | `doubao-seed-2.0-lite`（代码默认值，env `ROUTE_MODEL_NAME` 可覆盖） |
| Embedding | DashScope `qwen3.7-text-embedding` |
| MySQL | localhost:3306，数据库 `hotel`（17 表），DBUtils 连接池 max50 / mincached10 / maxcached20 |
| Checkpointer | **AsyncRedisSaver**（Redis 持久化，挂了自动退 InMemory）；langgraph 1.0.7 + langgraph-checkpoint 4.2.0 + langgraph-checkpoint-redis 0.5.2 |
| RAG 向量库 | Redis，索引 `kb_43`（知识库）+ `mem_43`（对话记忆冷层）（1024 维 / COSINE / FLAT）；语料 2 文件（表结构.txt=business / 业务知识通识.txt=hotel），tags.json 文件级登记 |
| Python 解释器 | `D:\Anaconda3_env\envs\lang_cg\python.exe` |
| 版本管理 | Git 已初始化（root commit 589e68b）；`.gitignore` 排除 `.env`、IDE 配置、缓存 |

**终端命令格式**：`& "D:/Anaconda3_env/envs/lang_cg/python.exe" "d:/xxx.py"`
（PowerShell 不支持 `&&` 作为语句分隔符，用 `;`）

**环境职责**：
- `D:\data-analysis-platform` = 开发测试环境，已用 Git 管理；`.env` 等敏感文件经 `.gitignore` 排除
- `D:\data-analysis-platform-github` = GitHub 上传专用版（**仅用户明确说"上传"时才动**）

---

## 四、待恢复上下文（下次接手先看这里）

**当前进度**：v2.x，连锁酒店管理助手。数据库 `hotel`（物理 17 表 = 可查 16 + 认证 1），数据 2024-08~2027-08 共 535 万行明细；登录 = 员工编号+密码（361 在职员工预置、初始密码 123456，老板账号=张建国/boss@hotel.demo（占位，演示要真发再换真实地址）），权限五级体系（level 随 JWT，route 唯一收口门）；RAG tag = business/hotel（tags.json 文件级登记）；三层记忆（热/温/冷 mem_43 向量库）。LangGraph 10 节点 / 4 agent（统一基类 BaseToolAgent）/ 3 Tool。

**酒店版验证（2026-10-01 晚）**：酒店版向量索引已用新语料重建跑通，SSE 全链路（查数 / 出图 / 追问 / HITL 邮件）端到端验证通过；修复前端「答完后输入框不解锁」——openSSE 由 async 改为同步返回 `{close}` handle（见踩坑段）；推荐问题中「本月/上月」改为「8月/7月」（月初演示有数据）。

**酒店化改造（2026-10-01 白天）**：库表/种子/RAG/prompt/前端整体酒店化 + 三项调整：① Agent prompt 去硬编码选表规则、② 恢复开放注册、③ RAG 第四章扩至 12 小节；Git 初始化（root commit 589e68b）。

**再前轮（2026-09-30）**：三层上下文记忆（memory_facts + 分块封存 + recall_history）；fetch POST 后端优化；默认时间口径只写两个 agent 的 prompt。

**遗留项**（以 devPlan.md 顶部为准）：
- P3 `context` 统一契约 —— 等第二个领域（律所/牙科）再抽象，见下方结论
- MessagesState 改造、requirements 钉版本、langchain-community 迁 partner 包、
  数据库层只读账号、tracing、登录防爆破（编号+密码错误限流） —— 均不阻塞面试

**用户已明确的暂缓项**：
- Neo4j、Ollama 换主模型 —— 评估后判定对当前场景提升很小，不做

**换行业的可行性结论**（用户提过「这套能用到律所/牙科」）：
实测有 **193 处硬编码领域知识**（mysql_tool 58 处、route 20 处、agent 24 处、
index.html 84 处）。建议**先硬做一版律所版，再回头抽 domain 层**，
不要先抽象——只有一个领域时抽出来的契约验证不了对不对。
