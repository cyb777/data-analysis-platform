# 基础编码提示词

> 本文档约束项目编码规范与质量要求，由人类维护，AI 开发时需严格遵守。

## 一、代码风格

- **编码**：全部文件 UTF-8 保存。
- **缩进**：Python 用 4 空格，不用 Tab。
- **命名**：
  - 变量/函数：snake_case（如 `build_graph`、`mysql_tool`）
  - 类名：PascalCase（如 `ChatRouter`、`RouteSchema`）
  - 常量：UPPER_SNAKE_CASE（如 `BASE_DIR`、`MAX_RETRY`）
  - 文件/目录：snake_case 或全小写（如 `chat_router.py`、`ai/agent`）
- **注释**：
  - 模块开头用 docstring 说明职责。
  - 关键逻辑加行内注释：实现陷阱（SDK 行为、占位符坑、框架机制）必须写；设计意图/权衡不写（归 devPlan.md / baseMem.md）。
  - 代码注释用中文，只描述当前行为（做什么、怎么用、实现陷阱）；版本演进/改动叙述不写进注释，统一留 devPlan.md。

## 二、架构约束

- **分层清晰**：
  - `app/ai/` — AI 核心（模型、工具、Schema、图、RAG）
  - `app/api/` — 接口层（路由、请求/响应模型）
  - `app/static/` — 前端静态资源
  - 不允许跨层直接调用（如 api 层不直接操作 ai/graph 内部细节）。
- **路由注册**：新接口在 `app/main.py` 的 `app.include_router()` 处注册。
- **环境变量**：敏感配置（API Key、数据库密码、邮箱密码、JWT_SECRET）放 `.env`，代码里用 `os.getenv()` 读取，不要硬编码。其中 JWT_SECRET 未配置（仍为默认值）时服务启动即拒，属有意 fail-fast。

## 三、AI 开发规范

- **改代码前**：先读 `baseInfo.md` 理解项目结构，再读相关模块代码。
- **改代码后**：更新 `baseMem.md` 记录变更内容。
- **不确定的改动**：先问人类，不要自行决定架构级变更。
- **测试**：改完接口要手动测一遍，确认能跑再提交。

## 四、Git 规范

- **提交信息**：简洁说明改了什么（如 `feat: 添加图表节点缓存`）。
- **分支**：功能开发用 feature 分支，合并后再删。
- **不要提交**：`.env`、`__pycache__/`、`.idea/`、`*.pyc`。

## 五、GitHub 上传规范

- **上传目录**：`D:\data-analysis-platform-github`（GitHub 专用版，含 Dockerfile、README.md）
- **上传时机**：仅在用户明确说"上传"时才执行，不要自动上传
- **上传流程**：
  1. 将 `D:\data-analysis-platform` 的最新代码同步到 `D:\data-analysis-platform-github`
  2. 排除 `.env`、`__pycache__/`、`.idea/`、`*.pyc`、`.codebuddy/` 等敏感/缓存文件
  3. 在 `D:\data-analysis-platform-github` 目录执行 git add/commit/push
- **注意**：`.env` 文件包含敏感配置（API Key、数据库密码、邮箱密码），绝对不能上传

## 六、常见陷阱

- **uvicorn reload=True**：Windows 下会因 `__pycache__` 文件变化触发重启导致崩溃，必须用 `reload=False`，改完代码手动 Ctrl+C 重启。
- **Redis 连接**：服务启动前必须确认 Redis 已运行，否则 RAG 向量库、Checkpointer、记忆冷层入库都会报错。注意 Redis 全挂时启动期建库会更早失败——checkpointer「挂了退 InMemory」只在窄故障面生效。
- **LangGraph 图构建**：`build_graph()` 在 lifespan 里执行，改图结构后需重启服务。
