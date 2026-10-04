# 聊天接口层：把 LangGraph 图封装成 SSE 流式接口
# SSE 帧类型（结构化数据直接推给前端渲染）：
#   type:text        → 文字回答
#   type:chart       → ECharts 图表 JSON
#   type:clarify     → 澄清反问标记（前端加输入提示，引导用户补充）
#   type:system      → 发邮件调度结果（"邮件已发至 X 收件人" + 收件人列表）
#   type:status      → 节点进度提示（"正在生成图表…"），只为消除空白等待，
#                      不进对话历史，被后续 text 帧覆盖即可
#   type:confirm     → HITL 邮件草稿确认（收件人/主题/正文 + 确定/取消按钮），
#                      system_send 节点 interrupt 挂起时推；用户点击后走 /chat/resume 恢复
import json
import re

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from langgraph.types import Command
from loguru import logger
from pydantic import BaseModel

from app.api.auth import get_optional_user   # JWT 校验（体验模式兼容）

chat_router = APIRouter()

# thread_id 允许的字符：字母数字、邮箱符号、下划线、横线（去掉空格和特殊符号防注入/超长）
_THREAD_SAFE_RE = re.compile(r"[^A-Za-z0-9_.@\-]")


def _namespaced_thread(user_id: int, raw_thread_id: str) -> str:
    """把客户端自报的 thread_id 服务端命名空间化。

    - 同一客户端值在不同用户下解析到不同物理线程，杜绝改 id 读他人历史/操作他人 HITL；
    - 匿名用户（user_id=0）单独一个 guest 命名空间，不与登录用户串；
    - 过滤非法字符。
    """
    safe = _THREAD_SAFE_RE.sub("", (raw_thread_id or "").strip())[:128] or "default"
    if user_id:
        return f"u{user_id}:{safe}"
    return f"guest:{safe}"


# POST 请求体（fetch 手写 SSE：不再用 query param 传 question）
class ChatRequest(BaseModel):
    question: str
    thread_id: str = "default"


class ResumeRequest(BaseModel):
    thread_id: str = "default"
    action: str = "cancel"

# 节点进度提示文案：整张图要跑几十秒，给每个节点配一句人话提示推 type:status 帧，
# 前端只显示最新一条、被真正的回答文字覆盖。
_NODE_STATUS_TIP = {
    "summarize": "正在整理对话上下文…",
    "route": "正在理解你的问题…",
    "rag": "正在检索业务口径资料…",
    "db": "正在查询数据库…",
    "chart": "正在生成图表…",
    "system_send": "正在发送邮件…",
    "writer": "正在撰写分析结论…",
    "chat": "正在组织回答…",
}

# 「下一步」提示：LangGraph 的 updates 事件是【节点执行完毕】才发的，
# 此时图表/数据其实已经有了，再说「正在生成图表」就和画面不符——
# 所以这些节点提示改成「接下来在等什么」（它们跑完一律汇入 writer 写分析）。
# 没列进来的节点保持原样：跑完后要么马上被下一个节点覆盖，要么本身就是最后一步。
_NEXT_STEP_TIP = {
    "chart": "正在撰写分析结论…",
    "db": "正在撰写分析结论…",
    "rag": "正在撰写分析结论…",
    # HITL：草稿节点跑完图就挂起等确认了，提示用户接下来该做什么
    "system_draft": "邮件草稿已就绪，请确认…",
    "system_send": "邮件已处理，正在整理结果…",
}


async def _sse_events(graph, stream, config):
    """共享 SSE 事件流（/chat 与 /chat/resume 复用同一套帧逻辑）。

    设计：
    - stream_mode=["updates","messages"] 混合模式：
      updates：每个节点跑完立刻拿到它的返回值 → chart_json 一到手就推 chart 帧；
      messages：只放行 writer/chat 节点的文字 token（内部节点结构化输出不适合直接给用户看）；
      每个节点跑完推 status 帧消除空白等待。
    - subgraphs=True 是流式的充分条件：AnlyzeAgent 由 create_agent 创建是【嵌套子图】，
      LangGraph 默认不向外转发子图内部的 messages 事件，不开就是「假流式」（整段弹出）。
    - 开了 subgraphs 后事件形状是 (namespace, mode, payload) 3 元组，根级事件 namespace 为空；
      namespace 形如 ('writer:<uuid>',)，冒号前就是外层节点名——用它区分是谁产出的。
      chart 子图也会冒 2 个 token（EchartsAgent 的结构化输出），必须过滤掉。
    """
    chart_sent = False
    streamed_chars = 0   # writer/chat 节点真正流出去的字数，决定末尾要不要兜底整段推
    async for event in stream:
        # subgraphs=True 下统一是 3 元组；这里仍兼容 2 元组，防止上游版本行为回退
        if len(event) == 3:
            namespace, mode, payload = event
        else:
            namespace, (mode, payload) = (), event
        # 外层节点名：子图事件取 namespace 前缀，根级事件取 metadata
        outer_node = namespace[0].split(":")[0] if namespace else ""

        if mode == "messages":
            msg = payload[0]
            metadata = payload[1] if len(payload) > 1 and isinstance(payload[1], dict) else {}
            node = outer_node or metadata.get("langgraph_node", "")
            # chat 节点（单次模型调用，不是子图）事件在根级，靠 metadata.langgraph_node 识别
            if node not in ("writer", "chat"):
                continue
            if msg.content:
                streamed_chars += len(msg.content)
                frame = {"type": "text", "content": msg.content, "done": False}
                yield f"data:{json.dumps(frame, ensure_ascii=False)}\n\n"
            continue

        # mode == "updates"：payload 形如 {节点名: 该节点返回的 state 增量}
        # 子图内部也会发 updates（如 writer/model、chart/tools），那些是智能体内部步骤，
        # 不是图节点，推给前端只会让 status 帧重复闪烁 → 只认根级（namespace 为空）。
        if namespace:
            continue
        for node_name, delta in (payload or {}).items():
            # route 跑完时按选定分支直接取下一节点提示（updates 是跑完才发，
            # 不这么做提示会停在「理解」，而实际已在取数）
            if node_name == "route" and isinstance(delta, dict):
                node_name = {
                    "db": "db", "rag": "rag", "chart": "chart",
                    "system": "system_draft", "chat": "chat",
                }.get(delta.get("route"), node_name)
            tip = _NEXT_STEP_TIP.get(node_name) or _NODE_STATUS_TIP.get(node_name)
            if tip:
                # 带上 node 名，前端据此渲染「进度步骤条」而不只是一句灰色文字
                frame = {"type": "status", "content": tip, "node": node_name, "done": False}
                yield f"data:{json.dumps(frame, ensure_ascii=False)}\n\n"
            if not isinstance(delta, dict):
                continue
            # 图表 JSON 一算出来就推，不等后面的分析文字
            chart = delta.get("chart_json")
            if chart and not chart_sent:
                chart_sent = True
                frame = {"type": "chart", "content": chart, "done": False}
                yield f"data:{json.dumps(frame, ensure_ascii=False)}\n\n"

    # ② 图跑完取最终 state，先看有没有挂起的 HITL 断点
    # 用异步 aget_state：checkpointer 是 AsyncRedisSaver 时同步 get_state 会直接报错
    final_state = await graph.aget_state(config)
    # interrupt 挂起时，最终 state 的 tasks 里带着 interrupt payload（邮件草稿）。
    # 必须最先检查：answer 是无 reducer 字段，上一轮的回答会在 values 里残留，
    # 不拦截的话会把旧回答当成这轮的结果推给前端。
    interrupts = [i for t in (final_state.tasks or []) for i in (t.interrupts or [])]
    if interrupts:
        frame = {"type": "confirm", "content": interrupts[0].value, "done": False}
        yield f"data:{json.dumps(frame, ensure_ascii=False)}\n\n"
        yield f"data:{json.dumps({'type': 'text', 'content': '', 'done': True}, ensure_ascii=False)}\n\n"
        return

    values = final_state.values or {}
    answer = values.get("answer")
    need_clarify = values.get("need_clarify", False)

    # 文字回答只在【零流式】时才整段推（开了 subgraphs 后 writer 逐字流出，
    # 再推一次整段前端会显示两遍）。兜底场景：clarify 直连 END 没有 token 可流、
    # 以及 writer 流式万一失败时还有内容兜住。
    if answer and streamed_chars == 0:
        frame = {"type": "text", "content": answer, "done": False}
        yield f"data:{json.dumps(frame, ensure_ascii=False)}\n\n"

    # 澄清标记帧（前端看到后可以引导输入，比如"请补充：时间/酒店/渠道"）
    # content 为空：帧本身只是「这是反问」的标记，反问内容在上面的 text 帧里。
    if need_clarify:
        frame = {"type": "clarify", "content": {}, "done": False}
        yield f"data:{json.dumps(frame, ensure_ascii=False)}\n\n"

    # 图表 JSON（chart 分支才非空）；上面 updates 里已推过就跳过
    chart = values.get("chart_json")
    if chart and not chart_sent:
        frame = {"type": "chart", "content": chart, "done": False}
        yield f"data:{json.dumps(frame, ensure_ascii=False)}\n\n"

    # 发邮件调度结果帧（system 分支才非空）
    #   前端识别后弹"邮件已发送"提示 + 显示收件人列表
    system_r = values.get("system_result") or {}
    if system_r.get("sent_count") is not None or system_r.get("summary"):
        frame = {"type": "system", "content": system_r, "done": False}
        yield f"data:{json.dumps(frame, ensure_ascii=False)}\n\n"

    # ③ 结束标识
    yield f"data:{json.dumps({'type': 'text', 'content': '', 'done': True}, ensure_ascii=False)}\n\n"


def _sse_response(graph, stream, config) -> StreamingResponse:
    """把共享事件流包成带异常兜底的 SSE 响应"""
    async def generator():
        try:
            async for frame in _sse_events(graph, stream, config):
                yield frame
        except Exception as e:
            import traceback
            logger.error(f"流式返回错误：{e}\n{traceback.format_exc()}")
            # 只回通用文案，异常原文只进服务端日志（防泄露内部地址/堆栈）
            yield f"data:{json.dumps({'type': 'text', 'content': '服务暂时出错，请稍后重试', 'done': True, 'error': True}, ensure_ascii=False)}\n\n"

    return StreamingResponse(content=generator(), media_type="text/event-stream")


@chat_router.post("/chat")
async def chat(request: Request, body: ChatRequest):
    """核心接口：POST /chat，JSON body: {question, thread_id}
    返回 SSE 流：文字(type:text) → 图表(type:chart) → 结束
    - 上下文压缩由 build.py 的 summarize 节点统一处理，本接口不重复做
    - JWT 接入：fetch 可自定义请求头，token 走标准 Authorization: Bearer。
      无 token → 体验模式（user_id=0，功能可用但身份不可信）；
      有 token → 必须合法（否则 401），身份以 token 为准，不接受 body 自报身份。
    """
    question, raw_thread_id = body.question, body.thread_id
    user = get_optional_user(request)
    user_id = user["user_id"] if user else 0
    graph = request.app.state.graph
    # thread_id 服务端命名空间化：客户端传同样的值，不同用户也落到不同物理线程
    thread_id = _namespaced_thread(user_id, raw_thread_id)
    config = {"configurable": {"thread_id": thread_id}}

    # HITL 卫生处理：这个线程若还挂着上次没确认的邮件断点，
    #   先按「取消」恢复并排空——带新输入 invoke 撞上 pending task 会报错。
    #   取消路径自写 answer 直连 END，不经过 writer，毫秒级完成。
    pending = await graph.aget_state(config)   # 同 aget_state 说明
    if any(t.interrupts for t in (pending.tasks or [])):
        logger.info(f"thread={thread_id} 有未确认的邮件草稿，按取消自动恢复")
        async for _ in graph.astream(Command(resume={"confirm": False}), config=config,
                                     stream_mode=["updates"]):
            pass

    stream = graph.astream({"question": question, "user_id": user_id},
                           config=config,
                           stream_mode=["updates", "messages"],
                           subgraphs=True)
    return _sse_response(graph, stream, config)


@chat_router.post("/chat/resume")
async def chat_resume(request: Request, body: ResumeRequest):
    """HITL 邮件确认的恢复接口。

    前端确认卡片点「确定发送 / 取消」→ fetch POST 打这里 → 图从 system_send 的
    interrupt 断点恢复：确认则群发邮件 + writer 润色，取消则直接答"已取消"。
    后续帧按 /chat 同一套 SSE 逻辑推流（_sse_events 共享）。

    action=confirm 发送，其他任何值一律取消（安全默认）。
    user_id 以断点时刻 checkpointer 里存的为准（发起时的真实身份），
    本接口只校验 token 合法，不接受客户端再报一次身份（防伪造）。
    """
    raw_thread_id, action = body.thread_id, body.action
    user = get_optional_user(request)   # 有 token 必须合法；无 token 体验模式也允许（同 /chat）
    user_id = user["user_id"] if user else 0
    graph = request.app.state.graph
    # 命名空间化后，别人即使把 thread_id 改成你的值，解析到的也是他自己的物理线程，
    # 下面的 interrupt 校验会发现没有断点可恢复——无法替你确认群发邮件。
    thread_id = _namespaced_thread(user_id, raw_thread_id)
    config = {"configurable": {"thread_id": thread_id}}

    # 归属/存在校验：只能恢复当前用户线程上真正挂着的断点
    pending = await graph.aget_state(config)
    if not any(t.interrupts for t in (pending.tasks or [])):
        logger.warning(f"thread={thread_id} 无挂起的邮件断点，拒绝 resume")
        raise HTTPException(status_code=404, detail="没有待确认的邮件草稿")

    stream = graph.astream(Command(resume={"confirm": action == "confirm"}),
                           config=config,
                           stream_mode=["updates", "messages"],
                           subgraphs=True)
    return _sse_response(graph, stream, config)
