"""聊天接口层：把 LangGraph 图封装成 SSE 流式接口。"""
import json

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse
from loguru import logger

chat_router = APIRouter()


@chat_router.get("/chat")
async def chat(request: Request, question: str, thread_id: str = "default"):
    """核心接口：GET /chat?question=...&thread_id=...
    返回 SSE 流：先逐字推文字回答（type:text），若走了 chart 分支再推一条图表 JSON（type:chart）
    """
    graph = request.app.state.graph
    config = {"configurable": {"thread_id": thread_id}}   # 多轮记忆按 thread_id 隔离

    async def generator():
        try:
            # ① 流式取 LLM 文字回答（边跑边吐）
            # stream_mode="messages"：模型每生成一个 token 就吐（打字机效果）
            # async for + yield：吐一个推一个给前端
            async for event in graph.astream({"question": question},
                                             config=config,
                                             stream_mode="messages"):
                msg = event[0]
                # stream_mode="messages" 会把【所有节点】的 LLM 输出都推过来，
                # 包括 route 节点的结构化输出（如 {"branch": "chart"}）——那只是内部路由结论，
                # 不能显示给用户。这里只放行最终回答节点 llm（AnalyzeAgent）的文字。
                metadata = event[1] if len(event) > 1 and isinstance(event[1], dict) else {}
                node = metadata.get("langgraph_node", "")
                if node and node != "llm":
                    continue
                if msg.content:
                    frame = {"type": "text", "content": msg.content, "done": False}
                    yield f"data:{json.dumps(frame, ensure_ascii=False)}\n\n"

            # ② 图跑完后取最终 state：先推文字答案，再推图表
            # graph.get_state(config)：图跑完了，看一下料包里最终存了什么
            #   state.answer     = llm 节点（AnalyzeAgent）生成的最终文字回答
            #   state.chart_json = chart 节点（EchartsAgent）生成的图表数据
            # 【为什么答案在这里整段推，而不是上面 ① 流式推？】
            #   因为 llm/db/chart 节点内部调的是"智能体"（agent.invoke 同步执行），
            #   那些 token 不经过 LangGraph 的流式通道，① 抓不到。
            #   所以最终答案等图跑完后从 state 里取出来，整段推给前端。
            final_state = graph.get_state(config)
            values = final_state.values or {}

            answer = values.get("answer")
            if answer:
                frame = {"type": "text", "content": answer, "done": False}
                yield f"data:{json.dumps(frame, ensure_ascii=False)}\n\n"

            chart = values.get("chart_json")
            if chart:
                frame = {"type": "chart", "content": chart, "done": False}
                yield f"data:{json.dumps(frame, ensure_ascii=False)}\n\n"

            # ③ 结束标识
            yield f"data:{json.dumps({'type': 'text', 'content': '', 'done': True}, ensure_ascii=False)}\n\n"

        except Exception as e:
            logger.error(f"流式返回错误：{e}")
            yield f"data:{json.dumps({'type': 'text', 'content': '服务出错', 'done': True, 'error': True}, ensure_ascii=False)}\n\n"

    return StreamingResponse(content=generator(), media_type="text/event-stream")
