# 智能体层：四个独立组件
#   EmailDispatcher    → 发邮件调度（system_draft / system_send 节点用）
#   SQLQuestionAgent → db 节点：查库 + 整理查询资料
#   EchartsAgent     → chart 节点：查库 + 生成 ECharts JSON
#   AnlyzeAgent      → writer 节点：综合分析汇总回答
# 图负责编排（路由/记忆/缓存/重试），这些智能体负责干活
