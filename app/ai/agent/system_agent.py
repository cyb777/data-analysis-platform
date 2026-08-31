"""登录验证码智能体：校验邮箱是否已注册，并发送验证码邮件。"""
from loguru import logger

from app.ai.model.model import MyModel
from app.ai.tool.mysql_tool import mysql_tool
from app.ai.tool.send_email_tool import send_email
from app.ai.schema.email_response import EmailResponse
from langchain.agents import create_agent


class SystemAgent:
    def __init__(self):
        logger.info("SystemAgent初始化")
        self.model = MyModel.get_model()
        self.tools = self.init_tools()
        self.agent = self.init_agent()

    def init_tools(self):
        self.tools = [mysql_tool, send_email]
        return self.tools

    def init_agent(self):
        prompt = """
        一:你是一个邮箱登录验证智能体,你有两个工具
            1.mysql_tool:用于执行sql查询
            2.send_email:用于发送验证码邮件
        二:你必须严格按照流程执行
            1.根据用户问题，调用mysql_tool查询 user_info 表，查询用户邮箱是否存在
            2.调用send_email发送邮件，内容是消息里给出的验证码（不要自己重新生成，原样使用）
        三:反馈信息
            1.如果 mysql_tool 工具 验证邮箱失败 ，返回状态码 500，验证码为0，提示信息 邮箱不存在
            2.如果 send_email 工具 发送邮件成功 ，返回状态码 200，提示信息 发送成功
            3.如果 send_email 工具 发送邮件失败 ，返回状态码 500，提示信息：失败原因说明
        """
        # response_format=EmailResponse：约束输出为 code/msg/verification_code 结构
        self.agent = create_agent(
            model=self.model,
            tools=self.tools,
            system_prompt=prompt,
            response_format=EmailResponse
        )
        return self.agent

    def answer(self, email: str, code: str):
        """执行"校验邮箱 → 发送验证码"流程

        :param email: 目标邮箱
        :param code: 验证码，由接口层生成并写入 Redis，智能体原样使用
        """
        rs = self.agent.invoke({"messages": [{"role": "user", "content": f"邮箱：{email}，验证码：{code}，请执行发送流程。"}]})
        answer = rs["structured_response"].model_dump()
        logger.info("智能体执行结果:{}", answer)
        return answer


if __name__ == '__main__':
    agent = SystemAgent()
    agent.answer("test@example.com", "123456")
