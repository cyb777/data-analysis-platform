# MySQL 数据访问层：连接池 + 只读护栏 + 游标样板收敛。
# 连接：DBUtils 连接池（双检锁单例）；只读护栏：sql_query_tool 拦截非只读语句；
# 游标样板收敛：query_all / query_one / execute_write 三函数统一连接获取与释放。
import os
import re
import threading
from dotenv import load_dotenv
from langchain.tools import tool
from loguru import logger
import pymysql
from dbutils.pooled_db import PooledDB
from app.ai.schemas.tool_sql_schema import MYsqlSchema

load_dotenv()

# 连接池全局变量（双检锁单例）
_pool = None
_pool_lock = threading.Lock()
_HAS_DBTUTILS = True



def _conn_kwargs():
    """MySQL 连接参数（连接池和单次直连共用，避免多处重复写 env 读取）"""
    return {
        "host": os.getenv("MYSQL_HOST"),
        "port": int(os.getenv("MYSQL_PORT") or 3306),
        "user": os.getenv("MYSQL_USER"),
        "password": os.getenv("MYSQL_PASSWORD"),
        "database": os.getenv("MYSQL_DATABASE"),
        "charset": "utf8mb4",
    }


def _get_pool():
    """线程安全的单例连接池：第一次调用时初始化，之后复用同一个池"""
    global _pool
    if _pool is None:
        with _pool_lock:
            if _pool is None:
                if not _HAS_DBTUTILS:
                    return None
                try:
                    _pool = PooledDB(
                        creator=pymysql,
                        # 池容量：maxconnections=50、mincached=10（首个请求不等建连接）、maxcached=20
                        maxconnections=50,
                        mincached=10,
                        maxcached=20,
                        blocking=True,         # 连接用完时阻塞等待（不是抛错）
                        **_conn_kwargs(),
                        cursorclass=pymysql.cursors.Cursor,
                    )
                    logger.info("MySQL 连接池初始化完成（mincached=10/maxconnections=50）")
                except Exception as e:
                    logger.error("MySQL 连接池初始化失败，退化为每次建连：{}", e)
    return _pool


def get_conn():
    """拿一个连接：有连接池走池（close 是还回池），没池退化为单次直连（close 是真断开）

    公开函数（无下划线前缀）：写操作方（send_email_tool 留痕 INSERT）
    也复用这个连接池。
    """
    pool = _get_pool()
    return pool.connection() if pool else pymysql.connect(**_conn_kwargs())


# ====== 游标样板收敛：统一连接获取、释放、commit，各处不再手写样板 ======

def _execute(cur, sql: str, params):
    """统一执行入口：params 为空时【不传】第二个参数给 pymysql。

    只要传了第二个参数（哪怕是空元组），pymysql 就会走 `sql % args` 格式化路径，
    于是 SQL 里的 `%` 会被当成占位符——而 LLM 写 `DATE_FORMAT(d, '%Y-%m-%d')`
    是家常便饭，会报 `not enough arguments for format string`。
    """
    if params:
        cur.execute(sql, params)
    else:
        cur.execute(sql)


def query_all(sql: str, params=None, dict_cursor: bool = False) -> list:
    """查多行：返回 list（dict_cursor=True 时每行是 dict，给前端接口用）"""
    con = get_conn()
    try:
        cur_cls = pymysql.cursors.DictCursor if dict_cursor else None
        with (con.cursor(cur_cls) if cur_cls else con.cursor()) as cur:
            _execute(cur, sql, params)
            return list(cur.fetchall())
    finally:
        con.close()


def query_one(sql: str, params=None, dict_cursor: bool = False):
    """查一行：返回一行（tuple 或 dict），没查到返回 None"""
    con = get_conn()
    try:
        cur_cls = pymysql.cursors.DictCursor if dict_cursor else None
        with (con.cursor(cur_cls) if cur_cls else con.cursor()) as cur:
            _execute(cur, sql, params)
            return cur.fetchone()
    finally:
        con.close()


def execute_write(sql: str, params=None) -> int:
    """写库（INSERT/UPDATE/DELETE）：自动 commit，返回 lastrowid（INSERT 用）"""
    con = get_conn()
    try:
        with con.cursor() as cur:
            _execute(cur, sql, params)
            last_id = cur.lastrowid
        con.commit()
        return last_id
    finally:
        con.close()


def _run_sql(sql: str) -> str:
    """统一执行 SQL 并把结果转成字符串给 LLM 看（连接获取/释放交给 query_all）"""
    try:
        return str(tuple(query_all(sql)))
    except Exception as e:
        logger.error("mysql 执行失败（sql前60字：{}）：{}", sql[:60], e)
        return f"查询失败：{e}"


@tool("sql_query", args_schema=MYsqlSchema)
def sql_query_tool(sql: str) -> str:
    """只读查询工具（护栏版）：执行 SELECT 查询，返回结果。
    只允许 SELECT/SHOW/DESCRIBE/EXPLAIN，非只读语句直接拦截。

    【本库全部表名和列名（以下是唯一可用的表，出现在这里之外的表名一律不存在）】
    - hotel 酒店门店表: hotel_id, hotel_name, city, district, star_level(2-5), room_count(可售房总数),
      floor_count, open_date, hotel_status(营业中/装修中/停业)
    - room_type 房型表: room_type_id, hotel_id, room_type_name(大床房/双床房/高级大床房/行政房/套房/亲子房),
      bed_type, area_sqm, standard_price(门市价), room_count(该房型间数), floor_no
    - guest 客户/会员表: guest_id, guest_name, phone, gender, register_date,
      member_level(普通/银卡/金卡/铂金/钻石), total_stay_nights, total_spent, stay_count,
      last_stay_date, preference
    - reservation 预订订单表: reservation_id, hotel_id, room_type_id, guest_id, channel_id,
      book_date, check_in_date, check_out_date, nights, room_count, booked_price(成交单价),
      total_amount(房费总额), order_status(已入住/已完成/已取消/未入住), cancel_date
    - stay_record 入住记录表（实际入住，OCC/ADR/RevPAR 一律以此表为准）: stay_id, reservation_id,
      hotel_id, room_type_id, guest_id, actual_check_in, actual_check_out, nights,
      adults, children, room_amount(实际房费)
    - channel 销售渠道表: channel_id, channel_name(散客上门/会员直订/携程/美团/飞猪/企业协议/旅行社团队/抖音),
      channel_type(直销/OTA/协议/旅行社), commission_rate(佣金率%)
    - payment 支付收入表: payment_id, hotel_id, guest_id, biz_type(房费/餐饮/增值服务),
      biz_id(对应单据ID), pay_time, amount, pay_method, pay_status(已支付/已退款/部分退款)
    - expense 成本支出表: expense_id, hotel_id, expense_date, expense_type(人力/水电/物料/能耗/维修/营销/租金/OTA佣金/折旧),
      amount, description
    - restaurant 餐厅表: restaurant_id, hotel_id, restaurant_name, cuisine_type(中餐/西餐/自助/大堂吧/日料),
      seat_count, meal_period
    - meal_order 餐饮订单表: meal_order_id, restaurant_id, hotel_id, guest_id, menu_item_id,
      diner_count, meal_time, amount, meal_type(早餐/午餐/晚餐/夜宵), pay_status(已支付/挂房账/免单)
    - menu_item 菜品表: menu_item_id, restaurant_id, dish_name, category(凉菜/热菜/主食/汤/甜点/酒水),
      price, cost, on_sale
    - service_order 增值服务订单表: service_order_id, hotel_id, guest_id, reservation_id,
      service_name(SPA/接送机/洗衣/迷你吧/会议室/加床), service_time, quantity, amount,
      order_status(待服务/已完成/已取消)
    - employee 员工表（业务员工档案）: employee_id, employee_name, hotel_id(总部为NULL),
      position, department(管理/前厅/客房/餐饮/工程/安保), phone, hire_date, employee_status(在职/离职)
    - service_record 服务记录表（员工对客服务执行记录）: record_id, hotel_id, employee_id, guest_id,
      service_type(客房清洁/开夜床/行李/叫醒/报修处理/迎宾), service_time, result(完成/未完成), remark
    - review_complaint 评价投诉表: review_id, hotel_id, guest_id, reservation_id, channel_id,
      review_type(好评/中评/差评/投诉), rating(1-5), category(卫生/设施/服务/噪音/早餐/位置/性价比),
      content, review_time, handle_status(待处理/处理中/已闭环)
    - user_info 系统登录账号表（只有在此表的人才能登录）: id, user_name, email,
      role(管理岗职位：分公司老板/区域经理/店长/前厅经理/客房经理/餐饮经理)
    - notification_record 邮件通知留痕表：每次发信自动写入，可 SELECT 查询

    常见错误提醒：没有 users / customer / orders / room / city 这些表；客户叫 guest（不是 customer/users），
    订单叫 reservation（不是 orders），房型叫 room_type（不是 room）；城市字段在 hotel.city（没有独立城市表）。
    表关联：reservation.hotel_id=hotel.hotel_id，reservation.room_type_id=room_type.room_type_id，
    reservation.guest_id=guest.guest_id，reservation.channel_id=channel.channel_id；
    stay_record 是实际入住口径；payment 用 biz_type+biz_id 关联房费/餐饮/增值服务单据。
    """
    sql_stripped = sql.strip().upper()
    # 放行只读元数据查询（SHOW TABLES / DESCRIBE / EXPLAIN），拦真正的写操作
    if not (sql_stripped.startswith("SELECT")
            or sql_stripped.startswith("SHOW")
            or sql_stripped.startswith("DESCRIBE")
            or sql_stripped.startswith("DESC ")
            or sql_stripped.startswith("EXPLAIN")):
        logger.warning("→ 只读护栏拦截了非只读语句：{}", sql[:50])
        return "（拒绝：只允许 SELECT/SHOW/DESCRIBE/EXPLAIN 等只读查询）"
    return _run_sql(_ensure_limit(sql))


# ====== SELECT 强制加 LIMIT 兜底：没写 LIMIT 的自动补（prompt 软约束不保证生效，这里做硬约束）======
MAX_ROWS = 100


def _ensure_limit(sql: str) -> str:
    """给没写 LIMIT 的 SELECT 自动补上 LIMIT 100（硬兜底，防止单次返回上万字）。

    只在确实安全的情况下补，下面几类【原样放行】：
      - 已经写了 LIMIT（不管在主查询还是子查询里，都不重复加）
      - 纯聚合查询（只有 COUNT/SUM/AVG/MAX/MIN，没有 GROUP BY）——结果本来就 1 行，
        补 LIMIT 没意义；而且这类 SQL 常被用来取单个数值（如总量/均值）
      - 非 SELECT 开头（SHOW/DESCRIBE/EXPLAIN 结果集本来就小）
    """
    s = sql.strip().rstrip(";").strip()
    upper = s.upper()

    if not upper.startswith("SELECT"):
        return sql
    # 已有 LIMIT 就不动。用正则而不是 `in`，避免匹配到列名里的 "limit"（如 usage_limit、min_stock）
    if re.search(r"\bLIMIT\s+\d+", upper):
        return sql
    # 纯聚合（无 GROUP BY）结果只有一行，不需要 LIMIT
    if not re.search(r"\bGROUP\s+BY\b", upper) and re.search(
            r"\bSELECT\s+(COUNT|SUM|AVG|MAX|MIN)\s*\(", upper):
        return sql

    # 常规兜底动作（email/chart 一次任务会连续跑多条 SELECT），不是异常，
    # 用 debug 级别避免刷屏；需要排查时把日志级别调到 DEBUG 即可看到。
    logger.debug("→ SQL 未写 LIMIT，自动补 LIMIT {} 防止返回过多数据", MAX_ROWS)
    return f"{s} LIMIT {MAX_ROWS}"


# ====== 列名自查工具（让 LLM 在不知道表结构时主动查）======
@tool("describe_table", parse_docstring=True)
def describe_table_tool(table_name: str) -> str:
    """查看指定表的实际列名和数据类型。
    用法：列名不确定时调用，例 describe_table("guest") → 返回 guest_id, guest_name, total_spent...

    可用表名只有这 17 个：hotel, room_type, guest, reservation, stay_record, channel,
    payment, expense, restaurant, meal_order, menu_item, service_order, employee,
    service_record, review_complaint, user_info, notification_record

    Args:
        table_name: 表名（必须是上面 17 个之一）
    """
    # 只允许字母数字下划线，防 SQL 注入
    if not table_name.replace("_", "").isalnum():
        return "（拒绝：表名只能包含字母数字下划线）"
    try:
        rows = query_all(f"DESCRIBE `{table_name}`")
        # 返回格式：列名(类型) 列表，方便 LLM 直接看懂
        return ", ".join(f"{r[0]}({r[1]})" for r in rows)
    except Exception as e:
        logger.error("describe_table 失败：{}", e)
        # 表名拼错时（1146）自动列出所有表，提示 LLM 用真名
        if "doesn't exist" in str(e) or "1146" in str(e):
            try:
                tables = [r[0] for r in query_all("SHOW TABLES")]
                return f"（表名 {table_name} 不存在！请使用以下真实表名之一：{', '.join(tables)}）"
            except Exception as e2:
                logger.error("SHOW TABLES 兜底也失败：{}", e2)
        return f"（查询失败：{e}）"
