# 模型层：管理模型实例，单例模式（整个程序只有一个主模型实例 + 一个路由轻量模型实例）
from langchain_openai import ChatOpenAI
import os
from dotenv import load_dotenv
load_dotenv()


class MyModel:
    # 单例模式：类变量挂在类上，全局只有一份
    _model = None
    _route_model = None

    @staticmethod
    def get_model():
        """主模型单例：第一次调用创建，之后复用（模型是收费资源，全局共用一个）"""
        if MyModel._model is None:
            # streaming=True：模型流式开关（图里直接能吐 token）
            # timeout=80：单次请求最多等 80 秒——agent 一次 invoke 内部多轮往返常跑几十秒，
            # 30 秒容易在中途超时并触发整个 agent 从头重跑（不设的话默认 10 分钟，API 挂起表现为服务卡死）
            # max_retries=1：网络抖动自动重试 1 次
            MyModel._model = ChatOpenAI(
                model=os.getenv("MODEL_NAME"),
                streaming=True,
                timeout=80,
                max_retries=1,
            )
        return MyModel._model

    @staticmethod
    def get_route_model():
        """路由专用轻量模型（默认 doubao-seed-2.0-lite，env ROUTE_MODEL_NAME 可覆盖）。

        route 是「从 7 个词里挑 1 个」的分类活，不用主模型；
        和主模型共用一套 OPENAI_API_BASE / OPENAI_API_KEY。
        不开 streaming（route 不需要流式输出），timeout=25：结构化输出内部还有一次
        schema 约束往返，15 秒在网关抖动/排队时容易误超时并退回关键词兜底，25 秒留余量。
        """
        if MyModel._route_model is None:
            model_name = os.getenv("ROUTE_MODEL_NAME", "doubao-seed-2.0-lite")
            MyModel._route_model = ChatOpenAI(
                model=model_name,
                streaming=False,
                timeout=25,
                max_retries=1,
            )
        return MyModel._route_model
