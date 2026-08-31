# -*- coding: utf-8 -*-
"""
基于 LangGraph 与 RAG 的多智能体问答平台 主入口（FastAPI 服务版）

把 LangGraph 图封装成可对外提供服务的接口平台：

  app/
  ├─ main.py                  ← 本文件：FastAPI 服务（lifespan 建图 + CORS + 注册路由）
  └─ ai/
      ├─ model/model.py       ← 模型封装
      ├─ tool/                ← 多工具：mysql_tool（查库）/ send_email_tool（发信）
      ├─ schema/              ← 结构化输出：Route / SQLQuery / ChartData / Email
      ├─ graph/               ← 图：state / nodes / build（含缓存+重试+记忆）
      └─ rag/knowledge_base.py← RAG：递归分块 → 向量化 → Redis 库 → 相似度检索
  └─ api/
      ├─ chat/chat_router.py  ← SSE 流式问答接口（文字 + 图表 type 分流）
      └─ system/system_router.py ← 邮箱验证码登录 / 注册鉴权

启动：python app/main.py   （Redis 必须开着，RAG 建库 + 验证码缓存都用它）
"""
import sys
from pathlib import Path

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from loguru import logger

from dotenv import load_dotenv

# 项目根目录 = app 的上一级；API key / 数据库 / 邮箱配置在项目根目录的 .env
BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))
load_dotenv(BASE_DIR / ".env", override=False)

logger.info("=" * 60)
logger.info("多智能体问答平台：RAG + NL2SQL + 图表 + 登录鉴权")
logger.info("=" * 60)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 服务启动时：构建 LangGraph 图（含 RAG 建库），挂到 app.state 上，接口里随时取
    from app.ai.graph.build import build_graph
    app.state.graph = build_graph()
    logger.info("LangGraph 图构建完成（RAG 向量库已加载）")
    yield
    logger.info("服务已销毁")


app = FastAPI(lifespan=lifespan)

# 跨域：允许前端访问（前端跑在哪个地址就加哪个，本地测试默认 8081）
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:8081", "http://127.0.0.1:8081"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 注册接口
from app.api.system.system_router import system_router
from app.api.chat.chat_router import chat_router

app.include_router(system_router)
app.include_router(chat_router)

# 同源托管前端页面（app/static/index.html），访问 http://localhost:8000 即可，不用另起 8081
STATIC_DIR = BASE_DIR / "app" / "static"
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/", include_in_schema=False)
async def index():
    return FileResponse(STATIC_DIR / "index.html")


if __name__ == "__main__":
    # 用 uvicorn 启动服务：python app/main.py
    import uvicorn
    # reload=False（重要）：Windows 下 reload=True 有两个坑——
    #   ① WatchFiles 监听整个项目目录，Python 运行生成的 __pycache__/*.pyc 也会触发重载
    #   ② 重载时要 os.kill(CTRL_C_EVENT)，Windows 下常抛 OSError [WinError 6] 句柄无效 → 服务崩溃
    # 结果就是"跑着跑着网页打不开"。开发时改完代码手动重启即可（Ctrl+C 再 python app/main.py）
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=False)
