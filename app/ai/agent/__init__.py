"""智能体层：四个独立 Agent。

   SystemAgent      → 登录验证码（api/system 用）
   SQLQuestionAgent → db 节点：查库 + 整理查询资料
   EchartsAgent     → chart 节点：查库 + 生成 ECharts JSON
   AnalyzeAgent     → llm 节点：综合分析汇总回答
图负责编排（路由/记忆/缓存/重试），智能体负责干活。
"""
