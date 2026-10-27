# 记忆域（mem_43）：对话冷层的向量化与三层记忆策略
#   history.py   冷层向量库（建/写/语义回查）——向量基建，复用 rag 包的 embedding/schema/rerank
#   compress.py  压缩层（分块判断 + 块压缩 + 事实合并）——summarize 节点专用
#   recall.py    组装与回查层（node_history_text 拼热层+温层 / recall_text 冷层回查，只有 chat 调）
