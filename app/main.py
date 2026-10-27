# -*- coding: utf-8 -*-
"""
数据分析平台 主入口（FastAPI 服务版）
=====================================================
把 LangGraph 图封装成可对外提供服务的接口平台：

  app/
  ├─ main.py                  ← 本文件：FastAPI 服务（lifespan 建图 + CORS + 注册路由）
  ├─ ai/
  │   ├─ model/model.py       ← 模型封装（单例 + 路由轻量模型）
  │   ├─ agent/               ← 四个智能体：SQLQuestion / Echarts / Anlyze / System（registry 单例）
  │   ├─ tool/                ← 工具层：mysql_tool（查库）/ data_calc_tool（精算）
  │   │                            email_material_tool（邮件全套：素材三件套 + SMTP 直发，后者非 @tool）
  │   ├─ rag/                 ← RAG 包：builder（建库管线/幂等增量）/ retriever（在线检索）
  │   ├─ mem/                 ← 记忆包：history（mem_43 冷层向量库）/ compress（压缩）/ recall（组装+回查）
  │   ├─ schemas/             ← 结构化输出/入参：Route / ChartData / 各工具入参 schema
  │   ├─ graph/               ← 图：state / build（缓存+重试+记忆装配）
  │   └─ nodes/               ← 10 个节点：summarize/route/rag/db/chart/clarify/system×2/writer/chat
  ├─ api/
  │   ├─ auth/                       ← auth 领域：jwt.py（签发/校验）+ password.py（PBKDF2）
  │   │                                + auth_router.py（员工编号登录/改密码/绑邮箱）
  │   ├─ chat/chat_router.py         ← SSE 流式问答接口（text/chart/clarify/system/status/confirm 帧）
  │   └─ schema/login_schema.py      ← 登录/账号请求结构
  └─ static/                  ← 前端页面（同源托管，访问 / 即可）

启动：python app/main.py   （Redis 必须开着，RAG 建库 + Checkpointer + 记忆冷层都用它）
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
logger.info("数据分析平台：RAG + NL2SQL + 多智能体 + 图表 + 登录鉴权")
logger.info("=" * 60)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # JWT_SECRET 弱默认值直接拒绝启动（先炸再建图，不白跑 RAG 建库）
    from app.api.auth.jwt import assert_secret_configured
    assert_secret_configured()
    # 服务启动时：构建 LangGraph 图（含 RAG 建库 + checkpoint 索引），挂到 app.state 上
    from app.ai.graph.build import build_graph
    app.state.graph = await build_graph()
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
from app.api.auth.auth_router import auth_router
from app.api.chat.chat_router import chat_router

app.include_router(auth_router)
app.include_router(chat_router)

# 同源托管前端页面（app/static/index.html），访问 http://localhost:8000 即可，不用另起 8081
STATIC_DIR = BASE_DIR / "app" / "static"
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/", include_in_schema=False)
async def index():
    """前端入口（禁缓存，避免改 HTML 后浏览器拿旧版）"""
    return FileResponse(
        STATIC_DIR / "index.html",
        headers={"Cache-Control": "no-store, no-cache, must-revalidate, max-age=0"},
    )


if __name__ == "__main__":
    # 用 uvicorn 启动服务：python app/main.py
    # reload 必须为 False：True 时 WatchFiles 监听整个项目目录，代码运行产生的
    # __pycache__/*.pyc 或文件修改都会触发自动重启；Windows 下重启时常报
    # OSError [WinError 6] 导致服务直接崩（表现为"跑着跑着网页打不开"）。
    # 改完代码手动 Ctrl+C 重启即可。
    import uvicorn
    uvicorn.run("app.main:app", host="localhost", port=8000, reload=False)
