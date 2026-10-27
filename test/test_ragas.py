"""RAGAS 四指标评测：知识库问答链（tag=hotel 检索 → 生成 → 四指标打分）

评什么：
  - 检索质量：Context Precision（相关段是否排前）/ Context Recall（参考答案所需信息是否都检索到）
  - 生成质量：Faithfulness（答案是否完全基于检索内容）/ Answer Relevancy（是否切题）

评测对象说明：
  - 四指标需要自然语言答案，因此只评「知识库问答链」（rag 节点 → writer），
    SQL 取数链的答案不是陈述句，不适用 Faithfulness 等生成指标。
  - 生成侧是对线上 rag→writer 的简化复刻：同一批召回片段 + 同一主模型（doubao-seed-1.6）
    直出答案，不带记忆/计算工具（单题评测用不到），口径与线上基本一致。

运行（需先开 Redis 容器）：
  D:/Anaconda3_env/envs/lang_cg/python.exe -X utf8 test/test_ragas.py

依赖：pip install ragas==0.3.9
  注意 ragas 0.3.9 顶层 import ChatVertexAI，而 langchain_community 0.3.31 已删除该模块；
  本脚本在 import ragas 前注入占位模块绕过（评委用豆包，永远不会实例化 ChatVertexAI）。

可复现性：每次运行先 FT.DROPINDEX 清空再重建 kb_43（51 段），
  避免服务多次重启累积的重复段影响检索公平性；对正在运行的服务无影响（内容一致）。
"""
import sys
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# --- 占位模块：绕过 ragas 0.3.9 对已删除的 langchain_community.chat_models.vertexai 的顶层 import ---
_shim = types.ModuleType("langchain_community.chat_models.vertexai")


class ChatVertexAI:  # noqa: D401 - 仅为占位，不会被实例化
    def __init__(self, *args, **kwargs):
        raise ImportError("ChatVertexAI 已从 langchain_community 移除；本评测使用豆包模型")


_shim.ChatVertexAI = ChatVertexAI
sys.modules["langchain_community.chat_models.vertexai"] = _shim

import redis  # noqa: E402

# 12 题评测集：question + 参考答案（ground truth 严格取自 业务知识通识.txt 原文口径，
# Context Recall 会把参考答案拆成陈述句逐条核对检索内容，因此措辞贴近原文）
EVAL_SET = [
    {
        "q": "RevPAR 怎么计算？它和 OCC、ADR 是什么关系？",
        "gt": "RevPAR（每间可售房收入）= 实际房费收入 / 可售间夜数，等价于 OCC × ADR。"
              "可售间夜数 = 房间数 × 统计天数。多门店汇总时不能简单平均各店 RevPAR，"
              "应使用总房费收入 / 总可售间夜数。",
    },
    {
        "q": "OCC 入住率是怎么计算的？多门店汇总时要注意什么？",
        "gt": "OCC = 实际售出间夜数 / 可售间夜数，实际售出间夜数取 stay_record.nights 之和，"
              "可售间夜数 = hotel.room_count × 统计天数；取消单和未入住单不计入，使用实际入住记录。"
              "多门店汇总时应分别按每家门店房间数计算可售间夜再求和，输出时乘 100 并 ROUND 成百分比。",
    },
    {
        "q": "什么是间夜？可售间夜怎么计算？",
        "gt": "间夜（Room Night）指一间客房被入住一晚，是酒店最基础的业务量单位，"
              "已售间夜数为 stay_record.nights 之和。可售间夜数 = 房间数 × 统计天数，"
              "例如 200 间房的酒店 9 月 30 天的可售间夜为 6000；严格口径应扣除维修房、停用房、自用房，"
              "本库简化为 room_count × 天数。",
    },
    {
        "q": "NoShow 是什么意思？酒店通常怎么处理？",
        "gt": "NoShow 指客人已预订但未到店、也没有取消。酒店通常按担保规则扣首晚房费；"
              "统计上 NoShow 率 = order_status='未入住' 的预订数 / 全部预订数，"
              "NoShow 单不计入实际入住（OCC 以 stay_record 实际入住为准）。"
              "酒店常用适度超售来对冲 NoShow 造成的空房损失。",
    },
    {
        "q": "会员复住率怎么算？流失预警一般怎么判断？",
        "gt": "会员复住看同一 guest_id 在 stay_record 中出现多次，住过两次及以上即复住。"
              "流失/沉睡预警按 guest.last_stay_date 距今天数判断，例如超过 180 天未住视为沉睡客户，"
              "可触发优惠券、积分、套餐等召回动作。",
    },
    {
        "q": "OTA 渠道和直销渠道有什么区别？各自的优劣是什么？",
        "gt": "OTA 是携程、美团、飞猪、抖音等在线旅行社平台，按成交房费收取 10%-20% 佣金，"
              "好处是带来曝光与异地/旅游增量客源，代价是佣金成本且客户被平台截留；"
              "直销是散客上门、会员直订、官网/小程序/电话预订，无佣金、客户可触达可复住，"
              "但需要自有会员体系与流量。优化方向是提升直销与会员占比、降低对高佣金 OTA 的依赖。",
    },
    {
        "q": "为什么 OCC 很高，RevPAR 却可能不高？",
        "gt": "因为 RevPAR = OCC × ADR，低价促销把入住率拉满时 ADR 会下滑，乘积可能不升反降。"
              "所以衡量经营要看 RevPAR 甚至 GOP，而不是只追求满房或单看房价。",
    },
    {
        "q": "什么是 GOP？酒店口径的 GOP 和利润有什么区别？",
        "gt": "GOP（经营毛利）= 收入 − 营业费用。严格酒店业口径下营业费用通常不含租金、折旧、"
              "财产税等业主固定费用，因此 GOP 反映经营管理成果，不等于净利润。"
              "本库可用 expense 排除租金、折旧后计算近似 GOP，GOP PAR（每间可售房 GOP）用于跨店盈利对比。",
    },
    {
        "q": "酒店一般有哪些手段提升 RevPAR？",
        "gt": "核心是在对的时间把对的房间以对的价格卖给对的客人：旺季提价、设连住/预付限制，"
              "淡季降价、套餐促销冲 OCC；用价格栅栏（提前预订、不可取消、连住、会员专享）区分价格敏感客群；"
              "给高价值渠道/房型保留房量、控制低价 OTA 放房数量；最终在低价满房与高价半空之间以 RevPAR"
              "（进一步以 GOP）最大化为准，而不是单纯追求 OCC 或 ADR。",
    },
    {
        "q": "差评和投诉的管理闭环流程是怎样的？",
        "gt": "闭环流程为：发现/接单 → 首次响应（SLA 限时，如投诉 24 小时内首次响应）→ 核实与补救 → "
              "内部定责改进 → 回访关单，状态从待处理、处理中到已闭环（review_complaint.handle_status）。"
              "差评率 = 差评数/评价总数，投诉闭环率 = 已闭环投诉/投诉总数；"
              "未闭环投诉是管理风险点，超时未处理应自动催办对应店长/前厅经理；"
              "OTA 差评需快速公开回复加私下补救。",
    },
    {
        "q": "餐饮的翻台率和客单价怎么计算？",
        "gt": "翻台率指餐位/餐桌在统计期内被重复使用的次数，本库可用就餐人数之和/餐位数近似上座率"
              "（SUM(diner_count)/seat_count，可按餐厅、日期、餐段统计）。客单价 = 餐饮收入/就餐人次；"
              "餐饮收入优先查 payment 中 biz_type='餐饮' 且已支付的金额，免单可计订单量但不计现金收入。",
    },
    {
        "q": "什么是超售？为什么要超售？有什么风险？",
        "gt": "超售（Overbooking）是为对冲 NoShow 而超额接受预订，可避免客人没来造成的空房损失；"
              "风险是超售过量导致到店客人多于房间，需要给客人升级房型或外送到其他酒店并补偿，"
              "严重伤害口碑，因此超售要适度。",
    },
]


def main():
    from app.ai.rag import builder, retriever
    from app.ai.rag.builder import REDIS_HOST, REDIS_PORT
    import os
    from langchain_openai import ChatOpenAI
    from app.ai.model.model import MyModel

    INDEX_NAME = builder.INDEX_NAME  # 建库管线内硬编码的索引名

    # 0) 清空并重建向量索引：保证 51 段无重复，评测可复现（内容与线上一致，不影响在跑的服务）
    r = redis.Redis(host=REDIS_HOST, port=int(REDIS_PORT), decode_responses=True)
    try:
        r.execute_command("FT.DROPINDEX", INDEX_NAME, "DD")
        print(f"已清空旧索引 {INDEX_NAME}")
    except Exception as e:
        print(f"无旧索引可清（首次运行属正常）: {str(e)[:80]}")
    retriever.set_vector_store(builder.build_vector_store())

    # 1) 检索 + 2) 生成（简化复刻 rag→writer：同一批召回片段 + 线上同款主模型单例直出）
    # 结果缓存到 output/ragas_raw.json：调评委参数重跑时不必再等生成阶段（删掉该文件可强制重跑全量）
    out_dir = Path(__file__).resolve().parent / "output"
    out_dir.mkdir(exist_ok=True)
    cache_path = out_dir / "ragas_raw.json"
    raw = []
    if cache_path.exists():
        import json
        raw = [tuple(x) for x in json.loads(cache_path.read_text(encoding="utf-8"))]
        print(f"命中缓存 {cache_path.name}：{len(raw)} 题，跳过检索+生成")
    else:
        gen_model = MyModel.get_model()
        print("\n----- 检索 + 生成 -----")
        for i, item in enumerate(EVAL_SET, 1):
            q = item["q"]
            # rag 节点同款调用（tag=hotel，只召回业务知识通识段），整块按 "\n---\n" 切回段列表
            block = retriever.retrieve_schema(q, tag_filter="hotel")
            contexts = [s for s in block.split("\n---\n") if s.strip()]
            prompt = (
                "你是连锁酒店经营分析助手。仅依据下面的检索资料回答用户问题，"
                "资料里没有的信息不要编造，不确定就说不确定。\n\n"
                f"检索资料：\n{block}\n\n用户问题：{q}"
            )
            answer = gen_model.invoke(prompt).content
            raw.append((q, answer, contexts, item["gt"]))
            print(f"[{i}/{len(EVAL_SET)}] {q[:24]}… 召回{len(contexts)}段，答案{len(answer)}字")
        import json
        cache_path.write_text(json.dumps(raw, ensure_ascii=False, indent=1), encoding="utf-8")

    # 3) RAGAS 四指标评测（评委=主模型同款 temperature=0，embedding 与线上一致 text-embedding-v4）
    from langchain_community.embeddings import DashScopeEmbeddings
    from ragas import EvaluationDataset, SingleTurnSample, evaluate
    from ragas.metrics import (
        AnswerRelevancy, Faithfulness, LLMContextPrecisionWithReference, LLMContextRecall,
    )
    from ragas.llms import LangchainLLMWrapper
    from ragas.embeddings import LangchainEmbeddingsWrapper
    from ragas.run_config import RunConfig

    # 评委：同 MODEL_NAME 但单独建 temperature=0 实例（不用 MyModel 单例，评委要稳定不要创作）
    # streaming=True：与线上主模型同理——豆包网关非流式长 prompt 容易撑满 timeout 触发重试，流式则 token 持续流动不超时
    # embedding 与线上一致：DASHSCOPE_MODEL_NAME（默认 text-embedding-v4）
    judge_llm = LangchainLLMWrapper(
        ChatOpenAI(model=os.getenv("MODEL_NAME"), temperature=0, streaming=True, timeout=120, max_retries=1)
    )
    judge_emb = LangchainEmbeddingsWrapper(
        DashScopeEmbeddings(
            model=os.getenv("DASHSCOPE_MODEL_NAME", "text-embedding-v4"),
            dashscope_api_key=os.getenv("DASHSCOPE_API_KEY"),
        )
    )
    samples = [
        SingleTurnSample(user_input=q, response=a, retrieved_contexts=c, reference=gt)
        for q, a, c, gt in raw
    ]
    print("\n----- RAGAS 评测（12 题 × 4 指标，12 并发，约 10 分钟）-----")
    result = evaluate(
        dataset=EvaluationDataset(samples=samples),
        metrics=[
            Faithfulness(llm=judge_llm),
            AnswerRelevancy(llm=judge_llm, embeddings=judge_emb),
            LLMContextRecall(llm=judge_llm),
            LLMContextPrecisionWithReference(llm=judge_llm),
        ],
        run_config=RunConfig(max_workers=12, timeout=300, max_retries=3),
    )

    df = result.to_pandas()
    print("\n===== 每题得分 =====")
    with __import__("pandas").option_context("display.max_colwidth", 28, "display.width", 200):
        print(df.to_string(index=False))
    print("\n===== 平均分 =====")
    print(df.select_dtypes("number").mean().round(4).to_string())
    out = Path(__file__).resolve().parent / "output" / "ragas_result.csv"
    df.to_csv(out, index=False, encoding="utf-8-sig")
    print(f"\n明细已存 {out}")


if __name__ == "__main__":
    main()
