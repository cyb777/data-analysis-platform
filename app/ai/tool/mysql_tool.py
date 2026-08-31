"""数据库工具：提供通用执行与只读查询两个版本。

- mysql_tool：可执行任意 SQL，供注册等写入场景使用
- sql_query_tool：只读护栏版，供智能体使用，非 SELECT 语句直接拦截
"""
from langchain.tools import tool
from loguru import logger

from app.ai.schema.sql_schema import MYsqlSchema
import os
from dotenv import load_dotenv
import pymysql

load_dotenv()


@tool("mysql", args_schema=MYsqlSchema)
def mysql_tool(sql: str) -> str:
    """
    执行MySQL查询语句，返回结果
    数据库模式：
    1. customer 客户表
       - user_id: 客户ID
       - username: 客户名
       - registration_date: 注册日期
       - country: 国家
       - age: 年龄
       - gender: 性别
       - total_spent: 消费总额
       - order_count: 订单数量

    2. customer_behavior 客户行为表
       - user_id: 客户ID
       - product_id: 产品ID
       - action: 行为类型：分为购买和浏览还有收藏
       - action_date: 行为日期
       - device: 设备

    3. orders 订单表
       - order_id: 订单ID
       - user_id: 客户ID
       - order_date: 订单日期
       - product_id: 产品ID
       - quantity: 数量
       - total_amount: 总金额
       - payment_method: 支付方式
       - order_status: 订单状态

    4. products 产品表
       - product_id: 产品ID
       - product_name: 产品名称
       - category: 类别
       - price: 价格
       - stock: 库存
       - sales_volume: 销量
       - average_rating: 平均评分

    5. sales 销售汇总表
       - year: 年份
       - total_sales: 总销售额
       - total_orders: 总订单数
       - total_quantity_sold: 总销量
       - category: 类别
       - average_order_value: 平均订单值

    6. user_info 用户表
       - id: 用户ID
       - user_name: 用户名
       - email: 邮箱
       - role: 角色
    """
    try:
        con = pymysql.connect(
            host=os.getenv("MYSQL_HOST"),
            port=int(os.getenv("MYSQL_PORT")),
            user=os.getenv("MYSQL_USER"),
            password=os.getenv("MYSQL_PASSWORD"),
            database=os.getenv("MYSQL_DATABASE"),
        )
        cur = con.cursor()
        cur.execute(sql)
        result = cur.fetchall()
        return str(result)
    except Exception as e:
        logger.error("mysql_tool 查询失败：{}", e)
        return "查询失败"


@tool("sql_query", args_schema=MYsqlSchema)
def sql_query_tool(sql: str) -> str:
    """只读查询工具（护栏版）：执行 SELECT 查询，返回结果。数据库模式同 mysql 工具。
    从源头禁止数据修改——非 SELECT 语句直接拦截，不碰数据库。"""
    if not sql.strip().upper().startswith("SELECT"):
        logger.warning("→ 只读护栏拦截了非 SELECT 语句：{}", sql[:50])
        return "（拒绝：只允许 SELECT 查询）"
    return mysql_tool.invoke({"sql": sql})
