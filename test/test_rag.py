"""功能测试：RAG 混合检索 / Schema 召回

会建向量库（调 embedding）并真跑「向量 + BM25 → RRF → rerank」全链路，
但不启服务、不打 SSE。检索不到 / 依赖缺失会明确报失败。

运行：
  D:/Anaconda3_env/envs/lang_cg/python.exe -X utf8 test/test_rag.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

PASS, FAIL = [], []


def check(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print(f"[{'OK' if ok else 'FAIL'}] {name}" + (f" -> {detail}" if detail else ""))


def main():
    from app.ai.rag import builder, retriever
    from app.ai.rag.builder import _tokenize

    print("\n----- 1. 分词 -----")
    toks = _tokenize("各渠道房费收入")
    check("分词返回 list", isinstance(toks, list) and len(toks) > 0, str(toks[:5]))

    print("\n----- 1.5 tag 规则与语料文件（离线）-----")
    kb = builder.KB_DIR
    # 指标口径与查询模板.txt = 表范围+强制口径+T1~T14 标准查询模板+查询规范，tags.json 登记 business
    check("指标口径与查询模板.txt 存在", (kb / "指标口径与查询模板.txt").exists())
    file_tags = builder._load_file_tags()   # _split_and_tag 需传 tags（循环外一次读入）
    chunks_s, metas_s = builder._split_and_tag(kb / "指标口径与查询模板.txt", file_tags)
    check("指标口径与查询模板.txt 全 business（tags.json 登记）", all(m["tag"] == "business" for m in metas_s))
    check("tags.json 已登记指标口径与查询模板.txt", builder._load_file_tags().get("指标口径与查询模板.txt") == "business")
    # 业务知识通识.txt：未登记走默认 hotel（business 才登记，hotel 免登记）
    chunks_h, metas_h = builder._split_and_tag(kb / "业务知识通识.txt", file_tags)
    check("业务知识通识.txt 全 hotel（默认）",
          bool(chunks_h) and all(m["tag"] == "hotel" for m in metas_h))
    # 拆分合并不丢内容：chunk 总数与语料规模相当（模板化重写后段数以实测为准，宽区间只防"丢内容"级事故）
    total = len(chunks_s) + len(chunks_h)
    check("chunk 总数≈语料规模", 30 <= total <= 70, str(total))

    print("\n----- 2. 建向量库 + 检索全链路 -----")
    retriever.set_vector_store(builder.build_vector_store())

    text = retriever.retrieve_schema("RevPAR 怎么算", tag_filter="hotel")
    check("retrieve_schema 返回非空 str",
          isinstance(text, str) and len(text.strip()) > 0, text[:60])

    # 业务口径召回（db/chart/email 共用入口；白名单机制已删——表列全量字典在 sql_query 工具说明）
    block = retriever.build_metric_block("8月入住率")
    check("build_metric_block 召回非空", bool(block and block.strip()), str(block)[:60])
    check("白名单机制已删（retrieve_schema_with_whitelist/_extract_columns 不存在）",
          not hasattr(retriever, "retrieve_schema_with_whitelist")
          and not hasattr(retriever, "_extract_columns"))
    # 认证表边界：召回段不得出现认证表列名（语料只留"不可查"声明、不列结构）
    check("召回段不含 password_hash（认证表结构不公开）",
          "password_hash" not in block)

    print("\n" + "=" * 60)
    print(f"通过 {len(PASS)} 项，失败 {len(FAIL)} 项")
    if FAIL:
        print("失败项：" + ", ".join(FAIL))
    print("=" * 60)
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
