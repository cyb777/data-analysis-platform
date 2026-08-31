"""模型封装：单例模式，确保整个程序只创建一个模型实例（节省资源/费用）。"""
from langchain_openai import ChatOpenAI
import os
from dotenv import load_dotenv

load_dotenv()


class MyModel:
    _model = None

    @staticmethod
    def get_model():
        if MyModel._model is None:
            # streaming=True 开启流式输出，配合图的 astream 实现打字机效果
            MyModel._model = ChatOpenAI(model=os.getenv("MODEL_NAME"), streaming=True)
        return MyModel._model
