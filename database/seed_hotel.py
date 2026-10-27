# -*- coding: utf-8 -*-
"""
连锁酒店管理助手 · 种子数据生成器（Python）

规模：10 家门店 × 三年（2024-08-01 ~ 2027-08-01，覆盖毕设答辩窗口）
特点：
  - 全部明细逐日生成：reservation / stay_record / payment / meal_order / expense
    所以 NL2SQL 跑「上月各店 OCC/RevPAR、近30天营收」都是真实聚合结果。
  - 真实节假日窗口：春节按 2025/2026/2027 实际日期（1/29、2/17、2/6 前后）+ 国庆/五一/元旦。
  - 幂等重建：每次运行先执行 database/schema.sql  DROP+CREATE 全部 17 张表再插入。
  - 账号体系：
    employee_id = 员工编号（入职年4+区域码2+部门码2+序号2，如 2018000101）；
    管理岗预绑邮箱（老板=boss@hotel.demo 占位，其余 emp{编号}@hotel.demo；要真发演示就把老板邮箱改成真实地址），员工岗留空（演示"未绑邮箱提醒"）；
    user_info 为纯认证表：在职员工全员账号，初始密码 123456（PBKDF2 每人独立盐）。

运行（conda lang_cg 环境）：
  D:/Anaconda3_env/envs/lang_cg/python.exe -X utf8 database/seed_hotel.py
"""
import hashlib
import os
import random
import sys
from datetime import datetime, date, time, timedelta
from pathlib import Path

import pymysql
from dotenv import load_dotenv

random.seed(43)

# ------------------------------------------------------------
# 0. 连接配置（读项目根目录 .env）
# ------------------------------------------------------------
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

DB_CONFIG = {
    "host": os.getenv("MYSQL_HOST", "localhost"),
    "port": int(os.getenv("MYSQL_PORT", "3306")),
    "user": os.getenv("MYSQL_USER", "root"),
    "password": os.getenv("MYSQL_PASSWORD", ""),
    "database": "hotel",
    "charset": "utf8mb4",
}

START = date(2024, 8, 1)
END = date(2027, 8, 1)           # 不含 END（数据止于 2027-07-31）

ALL_TABLES = [
    "notification_record", "user_info", "review_complaint", "service_record",
    "employee", "service_order", "menu_item", "meal_order", "restaurant",
    "expense", "payment", "channel", "stay_record", "reservation", "guest",
    "room_type", "hotel",
]

# ------------------------------------------------------------
# 公共缓冲/插入工具
# ------------------------------------------------------------
_buffers = {}


def add(table, row):
    _buffers.setdefault(table, []).append(row)


def flush_all(cur):
    cols_sql = {
        "hotel": ("hotel_id,hotel_name,city,district,star_level,room_count,"
                  "floor_count,open_date,hotel_status"),
        "room_type": ("room_type_id,hotel_id,room_type_name,bed_type,area_sqm,"
                      "standard_price,room_count,floor_no"),
        "guest": ("guest_id,guest_name,phone,gender,register_date,member_level,"
                  "total_stay_nights,total_spent,stay_count,last_stay_date,preference"),
        "channel": "channel_id,channel_name,channel_type,commission_rate",
        "reservation": ("reservation_id,hotel_id,room_type_id,guest_id,channel_id,"
                        "book_date,check_in_date,check_out_date,nights,room_count,"
                        "booked_price,total_amount,order_status,cancel_date"),
        "stay_record": ("stay_id,reservation_id,hotel_id,room_type_id,guest_id,"
                        "actual_check_in,actual_check_out,nights,adults,children,"
                        "room_amount"),
        "payment": ("payment_id,hotel_id,guest_id,biz_type,biz_id,pay_time,amount,"
                    "pay_method,pay_status"),
        "expense": "expense_id,hotel_id,expense_date,expense_type,amount,description",
        "restaurant": ("restaurant_id,hotel_id,restaurant_name,cuisine_type,"
                       "seat_count,meal_period"),
        "menu_item": ("menu_item_id,restaurant_id,dish_name,category,price,cost,on_sale"),
        "meal_order": ("meal_order_id,restaurant_id,hotel_id,guest_id,menu_item_id,"
                       "diner_count,meal_time,amount,meal_type,pay_status"),
        "service_order": ("service_order_id,hotel_id,guest_id,reservation_id,"
                          "service_name,service_time,quantity,amount,order_status"),
        "employee": ("employee_id,employee_name,hotel_id,position,department,"
                     "phone,hire_date,employee_status,email,level"),
        "service_record": ("record_id,hotel_id,employee_id,guest_id,service_type,"
                           "service_time,result,remark"),
        "review_complaint": ("review_id,hotel_id,guest_id,reservation_id,channel_id,"
                             "review_type,rating,category,content,review_time,"
                             "handle_status"),
        "user_info": "employee_id,password_hash",
    }
    total = 0
    for table, rows in _buffers.items():
        cols = cols_sql[table]
        n = cols.count(",") + 1
        sql = (f"INSERT INTO `{table}` ({cols}) VALUES "
               + ",".join(["(%s)" % ",".join(["%s"] * n)]))
        for i in range(0, len(rows), 1000):
            chunk = rows[i:i + 1000]
            cur.executemany(sql, chunk)
            total += len(chunk)
        rows.clear()
    return total


def weighted(weights):
    """返回命中的下标。weights: [(value, weight), ...]"""
    total = sum(w for _, w in weights)
    r = random.uniform(0, total)
    upto = 0
    for v, w in weights:
        upto += w
        if r <= upto:
            return v
    return weights[-1][0]


# ------------------------------------------------------------
# 1. 基础档案：hotel / room_type / channel / restaurant / menu_item
# ------------------------------------------------------------
HOTELS = [
    # id, 名称, 城市, 区, 星级, 房数, 楼层, 开业, 基础入住率
    (1,  "云栖国际酒店（上海南京路店）",   "上海", "黄浦区", 5, 220, 18, date(2018, 5, 18),  0.74),
    (2,  "云栖国际酒店（上海虹桥店）",     "上海", "闵行区", 4, 160, 12, date(2019, 9, 1),   0.70),
    (3,  "云栖大酒店（北京国贸店）",       "北京", "朝阳区", 5, 240, 22, date(2017, 3, 12),  0.72),
    (4,  "云栖大酒店（北京中关村店）",     "北京", "海淀区", 4, 180, 15, date(2020, 6, 28),  0.69),
    (5,  "云栖精选酒店（杭州西湖店）",     "杭州", "西湖区", 4, 150, 10, date(2019, 10, 1),  0.73),
    (6,  "云栖精选酒店（杭州钱江新城店）", "杭州", "上城区", 4, 140, 12, date(2021, 4, 16),  0.67),
    (7,  "云栖度假酒店（三亚海棠湾店）",   "三亚", "海棠区", 5, 200, 9,  date(2018, 12, 20), 0.66),
    (8,  "云栖度假酒店（成都春熙路店）",   "成都", "锦江区", 4, 130, 11, date(2020, 8, 8),   0.71),
    (9,  "云栖快捷酒店（广州天河店）",     "广州", "天河区", 3, 120, 8,  date(2021, 7, 1),   0.75),
    (10, "云栖快捷酒店（深圳北站店）",     "深圳", "龙华区", 3, 118, 9,  date(2022, 1, 15),  0.73),
]

# 房型模板：(名称, 床型, 面积, 基础价系数, 房间占比)
ROOM_TEMPLATES = [
    ("大床房",   "大床", 28, 1.00, 0.31),
    ("双床房",   "双床", 30, 1.05, 0.30),
    ("高级大床房", "大床", 35, 1.35, 0.16),
    ("行政房",   "大床", 42, 1.75, 0.10),
    ("套房",     "大床", 60, 2.60, 0.06),
    ("亲子房",   "双床", 45, 1.55, 0.04),
    ("家庭房",   "双床", 48, 1.45, 0.03),
]

# 渠道：id, 名称, 类型, 佣金率, 占比, 取消率
CHANNELS = [
    (1, "散客上门",   "直销",   0.0,  0.08, 0.02),
    (2, "会员直订",   "直销",   0.0,  0.24, 0.05),
    (3, "携程",       "OTA",   15.0,  0.24, 0.12),
    (4, "美团",       "OTA",   12.0,  0.18, 0.11),
    (5, "飞猪",       "OTA",   12.0,  0.10, 0.12),
    (6, "企业协议",   "协议",   3.0,  0.10, 0.04),
    (7, "旅行社团队", "旅行社", 8.0,  0.04, 0.06),
    (8, "抖音",       "OTA",   10.0,  0.02, 0.13),
]

MENU = [
    # （菜名, 分类, 基础价）——60 道池子，每店中餐厅随机抽 85% 上架（店与店菜单不同）
    # 凉菜 ×10
    ("凉拌黄瓜", "凉菜", 22), ("口水鸡", "凉菜", 38), ("盐水鸭", "凉菜", 42),
    ("老醋花生", "凉菜", 18), ("凉拌木耳", "凉菜", 20), ("酱牛肉", "凉菜", 48),
    ("夫妻肺片", "凉菜", 46), ("泡椒凤爪", "凉菜", 32), ("凉拌海蜇", "凉菜", 36),
    ("卤水拼盘", "凉菜", 58),
    # 热菜 ×20
    ("糖醋里脊", "热菜", 58), ("宫保鸡丁", "热菜", 42), ("清蒸鲈鱼", "热菜", 88),
    ("蒜蓉西兰花", "热菜", 32), ("东坡肉", "热菜", 68), ("小炒黄牛肉", "热菜", 78),
    ("番茄炒蛋", "热菜", 28), ("白灼虾", "热菜", 98), ("麻婆豆腐", "热菜", 30),
    ("红烧狮子头", "热菜", 48), ("黑椒牛柳", "热菜", 72), ("香辣蟹", "热菜", 128),
    ("蒜蓉粉丝蒸扇贝", "热菜", 88), ("干煸豆角", "热菜", 32), ("鱼香肉丝", "热菜", 38),
    ("回锅肉", "热菜", 46), ("蚝油生菜", "热菜", 26), ("铁板豆腐", "热菜", 36),
    ("姜葱炒花蛤", "热菜", 58), ("松鼠桂鱼", "热菜", 118),
    # 主食 ×8
    ("扬州炒饭", "主食", 28), ("牛肉拉面", "主食", 32), ("水饺(一份)", "主食", 26),
    ("云吞面", "主食", 30), ("干炒牛河", "主食", 36), ("腊味煲仔饭", "主食", 42),
    ("葱油拌面", "主食", 22), ("鲜肉小笼包", "主食", 24),
    # 汤 ×6
    ("酸辣汤", "汤", 22), ("老鸭煲", "汤", 68), ("玉米排骨汤", "汤", 48),
    ("紫菜蛋花汤", "汤", 18), ("松茸鸡汤", "汤", 58), ("西湖牛肉羹", "汤", 28),
    # 甜点 ×8
    ("酒酿圆子", "甜点", 18), ("提拉米苏", "甜点", 32), ("芒果布丁", "甜点", 22),
    ("红豆双皮奶", "甜点", 20), ("杨枝甘露", "甜点", 26), ("绿豆糕", "甜点", 16),
    ("蛋挞", "甜点", 12), ("水果拼盘", "甜点", 38),
    # 酒水 ×8
    ("可乐", "酒水", 8), ("鲜榨橙汁", "酒水", 18), ("本地啤酒", "酒水", 15),
    ("红酒(杯)", "酒水", 48), ("雪碧", "酒水", 8), ("酸梅汤", "酒水", 12),
    ("龙井茶(壶)", "酒水", 38), ("咖啡", "酒水", 22),
]

# 早餐池 ×14（早餐厅全量上架）
BREAKFAST_MENU = [
    ("白粥小菜套餐", "主食", 18), ("鲜肉包(个)", "主食", 6), ("豆浆油条", "主食", 12),
    ("鸡蛋面", "主食", 15), ("三明治", "主食", 20), ("水果拼盘", "甜点", 15),
    ("煎蛋培根套餐", "主食", 28), ("小馄饨", "主食", 16), ("牛奶燕麦粥", "主食", 14),
    ("葱花饼", "主食", 8), ("玉米棒", "主食", 6), ("酸奶杯", "甜点", 12),
    ("咖啡", "酒水", 12), ("果汁", "酒水", 10),
]

PREFERENCES = ["无烟房", "高楼层", "安静朝向", "靠近电梯", "双床", "大床",
               "需要婴儿床", "城市景观", "远离电梯", "早起送早餐",
               "连通房", "乳胶枕", "靠近健身房", "带宠物"]


def build_base():
    for (hid, name, city, dist, star, rooms, floors, open_d, _base) in HOTELS:
        add("hotel", (hid, name, city, dist, star, rooms, floors, open_d, "营业中"))

    rt_id = 1
    hotel_room_types = {}
    for (hid, _n, _c, _d, star, rooms, _f, _o, _b) in HOTELS:
        price_base = {3: 260, 4: 420, 5: 680}[star]
        types = []
        allocated = 0
        for idx, (rn, bed, area, k, ratio) in enumerate(ROOM_TEMPLATES):
            # 3 星级不配行政/套房（套房保留少量）
            if star == 3 and rn == "行政房":
                continue
            cnt = max(4, round(rooms * ratio)) if idx < len(ROOM_TEMPLATES) - 1 else None
            if cnt is None:
                cnt = rooms - allocated
            cnt = min(cnt, rooms - allocated)
            if cnt <= 0:
                continue
            std_price = round(price_base * k * random.uniform(0.95, 1.08), 0)
            add("room_type", (rt_id, hid, rn, bed, area, std_price, cnt,
                              f"{random.randint(3, max(3, 1))}-{18}"))
            types.append((rt_id, rn, std_price, cnt))
            allocated += cnt
            rt_id += 1
        # 修正尾差
        if types and allocated != rooms:
            first = types[0]
            delta = rooms - allocated
            for i, t in enumerate(types):
                if t[0] == first[0]:
                    types[i] = (t[0], t[1], t[2], t[3] + delta)
        hotel_room_types[hid] = types

    for cid, cname, ctype, comm, _r, _cancel in CHANNELS:
        add("channel", (cid, cname, ctype, comm))

    # 餐厅：4/5 星酒店各 2 个（自助早餐厅 + 中餐厅），3 星 1 个早餐厅
    rest_id = 1
    hotel_rests = {}
    for (hid, _n, _c, _d, star, _r, _f, _o, _b) in HOTELS:
        rests = []
        # 自助早餐厅
        add("restaurant", (rest_id, hid, "自助早餐厅", "自助",
                           120 if star >= 4 else 60, "早餐"))
        rests.append((rest_id, "自助早餐厅"))
        rest_id += 1
        if star >= 4:
            add("restaurant", (rest_id, hid, "云栖中餐厅", "中餐",
                               80 if star == 4 else 120, "午餐,晚餐"))
            rests.append((rest_id, "云栖中餐厅"))
            rest_id += 1
        hotel_rests[hid] = rests

    # 菜品：中餐厅从 60 道池子随机抽 85% 上架（店与店菜单不同），早餐厅全量 14 项
    mi_id = 1
    for (hid, _n, _c, _d, star, _r, _f, _o, _b) in HOTELS:
        for rid, rname in hotel_rests[hid]:
            if rname == "云栖中餐厅":
                for dish, cat, base_price in MENU:
                    if random.random() > 0.85:
                        continue  # 15% 菜品本店不上架
                    price = round(base_price * {4: 1.0, 5: 1.25}[star], 0)
                    add("menu_item", (mi_id, rid, dish, cat, price,
                                      round(price * random.uniform(0.30, 0.45), 2), 1))
                    mi_id += 1
            else:
                for dish, cat, base_price in BREAKFAST_MENU:
                    add("menu_item", (mi_id, rid, dish, cat, base_price,
                                      round(base_price * 0.4, 2), 1))
                    mi_id += 1

    return hotel_room_types, hotel_rests


# ------------------------------------------------------------
# 2. guest 客户池 40000
# ------------------------------------------------------------
SURNAMES = list("王李张刘陈杨黄赵吴周徐孙马朱胡郭何高林罗郑梁谢宋唐许韩冯邓曹彭")
GIVEN1 = list("伟芳娜秀英敏静丽强磊军洋勇艳杰娟涛明超秀兰霞平刚桂英华建文玉金国")
GIVEN2 = ["", "", "", "子", "雨", "梓", "浩", "欣", "怡", "晨"]


def rand_name():
    return random.choice(SURNAMES) + random.choice(GIVEN1) + random.choice(GIVEN2)


def build_guests():
    phones = set()
    guests = []
    for gid in range(1, 40001):
        while True:
            p = "1" + str(random.randint(30, 99)) + "".join(
                str(random.randint(0, 9)) for _ in range(9))
            if p not in phones:
                phones.add(p)
                break
        # 注册日期：70% 落在数据区间内，30% 更早的老客
        if random.random() < 0.7:
            reg = START + timedelta(days=random.randint(0, 600))
        else:
            reg = date(2021, 1, 1) + timedelta(days=random.randint(0, 1300))
        if reg > END:
            reg = END - timedelta(days=1)
        level = weighted([("普通", 55), ("银卡", 25), ("金卡", 13),
                          ("铂金", 5), ("钻石", 2)])
        gender = random.choice(["男", "女"])
        guests.append([gid, rand_name(), p, gender, reg, level,
                       0, 0.0, 0, None,
                       random.choice(PREFERENCES) if random.random() < 0.5 else None])
    for g in guests:
        add("guest", tuple(g))
    return guests


# ------------------------------------------------------------
# 3. employee 业务员工（编号=入职年+区域码+部门码+序号；level 按职位；管理岗预绑邮箱）
# ------------------------------------------------------------
POS_BY_DEP = {
    "管理": ["店长", "前厅经理", "客房经理"] + (["餐饮经理"]),
    "前厅": ["前台", "礼宾"],
    "客房": ["客房服务员", "保洁"],
    "餐饮": ["厨师", "厨师", "服务员"],
    "工程": ["工程维修"],
    "安保": ["安保"],
}

# 每家店各部门基础人数（会按星级增减）
DEP_STAFF = {
    "管理": 3, "前厅": 6, "客房": 12, "餐饮": 8, "工程": 2, "安保": 3,
}

# 编号码表（与 schema.sql 定稿一致）：区域码 2 位 + 部门码 2 位
CITY_REGION = {"北京": "01", "上海": "02", "广州": "03", "深圳": "04",
               "成都": "05", "杭州": "06", "三亚": "07"}
DEP_CODE = {"管理": "01", "前厅": "02", "客房": "03",
            "餐饮": "04", "工程": "05", "安保": "06"}
# 级别规则：老板岗=4，经理岗=3，其余正式员工=2（新入职默认 1 走库默认值，种子数据都是老员工）
BOSS_POS = {"分公司老板", "区域经理"}
MGR_POS = {"店长", "前厅经理", "客房经理", "餐饮经理"}

_HOTEL_CITY = {h[0]: h[2] for h in HOTELS}
_emp_seq = {}


def _emp_code(hire: date, hotel_id, dep: str) -> int:
    """员工编号 = 入职年(4) + 区域码(2) + 部门码(2) + 同(年+区域+部门)组内序号(2)"""
    region = "00" if hotel_id is None else CITY_REGION[_HOTEL_CITY[hotel_id]]
    key = (hire.year, region, DEP_CODE[dep])
    _emp_seq[key] = _emp_seq.get(key, 0) + 1
    return int(f"{hire.year}{region}{DEP_CODE[dep]}{_emp_seq[key]:02d}")


def build_employees():
    """生成员工并返回 (各店在职员工映射, 全部在职员工编号清单)——后者给 user_info 建账号"""
    hotel_emps = {}
    active_codes = []

    def add_emp(nm, hid, pos, dep, hire, status):
        code = _emp_code(hire, hid, dep)
        level = 4 if pos in BOSS_POS else (3 if pos in MGR_POS else 2)
        if nm == "张建国":
            email = "boss@hotel.demo"           # 占位邮箱（HITL 演示要真发就改成真实地址）
        elif pos in BOSS_POS or pos in MGR_POS:
            email = f"emp{code}@hotel.demo"     # 管理岗预绑占位邮箱（编号保证唯一）
        else:
            email = None                        # 员工岗留空：演示"对方未绑邮箱"提醒
        row = (code, nm, hid, pos, dep,
               "13" + str(random.randint(0, 9)) + "".join(
                   str(random.randint(0, 9)) for _ in range(8)),
               hire, status, email, level)
        add("employee", row)
        if status == "在职":
            active_codes.append(code)
        return row

    # 总部（hotel_id=NULL，区域码 00）：分公司老板 + 3 名区域经理
    hq = [("张建国", "分公司老板", "管理"),
          ("李振华", "区域经理", "管理"),
          ("王晓峰", "区域经理", "管理"),
          ("陈立群", "区域经理", "管理")]
    for nm, pos, dep in hq:
        hire = date(2017, 1, 1) + timedelta(days=random.randint(0, 2000))
        add_emp(nm, None, pos, dep, hire, "在职")

    for (hid, _n, _c, _d, star, _r, _f, _o, _b) in HOTELS:
        emps = []
        mult = {3: 0.7, 4: 1.0, 5: 1.25}[star]
        for dep, base in DEP_STAFF.items():
            n = max(1, round(base * mult))
            for pos in POS_BY_DEP[dep]:
                # 管理岗每类 1 人（餐饮经理仅 4/5 星）
                if dep == "管理":
                    if pos == "餐饮经理" and star == 3:
                        continue
                    cnt = 1
                else:
                    cnt = max(1, round(n / len(POS_BY_DEP[dep])))
                for _ in range(cnt):
                    hire = START - timedelta(days=random.randint(0, 1800))
                    emps.append(add_emp(rand_name(), hid, pos, dep, hire, "在职"))
        # 少量离职员工（不建账号、不绑邮箱）
        for _ in range(3):
            dep = random.choice(["客房", "前厅", "餐饮"])
            pos = random.choice(POS_BY_DEP[dep])
            add_emp(rand_name(), hid, pos, dep,
                    START + timedelta(days=random.randint(0, 400)), "离职")
        hotel_emps[hid] = emps
    return hotel_emps, active_codes


# ------------------------------------------------------------
# 4. 入住率与季节因子
# ------------------------------------------------------------
# 真实节假日窗口（起止含两端）：春节按 2025/2026/2027 实际日期，不再写死"2月前10天"
_HOLIDAY_WINDOWS = [
    # 国庆
    (date(2024, 10, 1), date(2024, 10, 7)),
    (date(2025, 10, 1), date(2025, 10, 7)),
    (date(2026, 10, 1), date(2026, 10, 7)),
    # 春节（除夕前一天 ~ 初六）
    (date(2025, 1, 28), date(2025, 2, 4)),    # 2025 春节 1/29
    (date(2026, 2, 16), date(2026, 2, 23)),   # 2026 春节 2/17
    (date(2027, 2, 5), date(2027, 2, 11)),    # 2027 春节 2/6
    # 五一
    (date(2025, 5, 1), date(2025, 5, 5)),
    (date(2026, 5, 1), date(2026, 5, 5)),
    (date(2027, 5, 1), date(2027, 5, 5)),
    # 元旦
    (date(2025, 1, 1), date(2025, 1, 3)),
    (date(2026, 1, 1), date(2026, 1, 3)),
    (date(2027, 1, 1), date(2027, 1, 3)),
]


def seasonal_factor(d: date):
    m = d.month
    # 三亚：冬季旺夏季淡；其他城市：节假/暑期旺
    base = {
        1: 0.92, 2: 0.95, 3: 0.88, 4: 0.95, 5: 1.02,
        6: 0.95, 7: 1.08, 8: 1.10, 9: 0.95, 10: 1.05,
        11: 0.92, 12: 0.98,
    }[m]
    # 法定节假日窗口加成（国庆/春节/五一/元旦）
    if any(a <= d <= b for a, b in _HOLIDAY_WINDOWS):
        base += 0.12
    if d.weekday() >= 5:
        base += 0.06
    else:
        base -= 0.02
    return base


def sanya_factor(d: date):
    if d.month in (11, 12, 1, 2):
        return 1.18
    if d.month in (6, 7, 8, 9):
        return 0.72
    return 0.95


def occ_for_hotel(hid, d, base_occ):
    f = sanya_factor(d) if hid == 7 else seasonal_factor(d)
    occ = base_occ * f + random.uniform(-0.04, 0.04)
    return min(0.97, max(0.38, occ))


# 渠道成交价系数（相对门市价）
CH_PRICE_K = {1: 1.05, 2: 0.88, 3: 0.82, 4: 0.80, 5: 0.83,
              6: 0.75, 7: 0.62, 8: 0.78}

LEAD_DAYS = {1: 0, 2: (0, 14), 3: (1, 30), 4: (0, 25), 5: (1, 30),
             6: (3, 45), 7: (7, 60), 8: (1, 20)}

NIGHT_WEIGHTS = [(1, 38), (2, 30), (3, 16), (4, 8), (5, 4), (6, 2), (7, 2)]

PAY_METHODS = [("微信", 38), ("支付宝", 30), ("银行卡", 20),
               ("现金", 5), ("挂账", 7)]

SVC_ITEMS = [
    ("SPA", (198, 598)), ("接送机", (80, 260)), ("洗衣", (25, 90)),
    ("迷你吧", (15, 60)), ("会议室", (800, 3000)), ("加床", (120, 200)),
    ("亲子乐园", (58, 128)), ("商务中心", (50, 200)), ("租车", (150, 400)),
    ("行李寄存", (10, 30)),
]

# 评价：按类别配对好/差评话术（差评内容和类别对得上，不再全库 8 条反复复用）
REVIEW_CATS = ["卫生", "设施", "服务", "噪音", "早餐", "位置", "性价比"]
CAT_WORDS = {
    "卫生": {
        "good": ["房间干净整洁，入住体验很好", "卫生间一尘不染，住着很放心", "床品干净，睡得很安稳"],
        "bad": ["房间有异味，卫生需要加强", "床单上有头发，体验很差", "卫生间角落有霉点，清洁不到位"],
    },
    "设施": {
        "good": ["设施很新，房间设备齐全好用", "空调制冷快，热水来得也快", "床垫很舒服，设施维护得好"],
        "bad": ["设施偏旧，希望尽快翻新", "空调噪音大影响休息", "电梯高峰期等太久"],
    },
    "服务": {
        "good": ["前台服务热情，办理速度快", "客房打扫及时，阿姨很用心", "礼宾帮忙拿行李，很贴心"],
        "bad": ["等房等了一个多小时", "退房排队太久，前台人手不足", "打电话到前台很久没人接"],
    },
    "噪音": {
        "good": ["房间很安静，休息得特别好", "朝向内庭，晚上一点不吵"],
        "bad": ["隔壁太吵，隔音一般", "临街房间车流声很明显", "楼道半夜还有喧哗声"],
    },
    "早餐": {
        "good": ["早餐品种丰富，味道不错", "早餐现煮档口很赞"],
        "bad": ["早餐品种太少，补充不及时", "早餐高峰期找不到位子", "早餐九点就没什么可吃的了"],
    },
    "位置": {
        "good": ["位置方便，出门就是商圈", "离地铁近，出行很方便", "海景房视野太棒了"],
        "bad": ["位置有点偏，打车不方便", "周边吃饭选择太少"],
    },
    "性价比": {
        "good": ["性价比高，下次还会来", "这个价位能住到很值"],
        "bad": ["价格偏贵，性价比一般", "旺季涨价有点狠"],
    },
    "整体": {
        "good": ["整体很满意，推荐入住", "床品舒适，睡得很好", "出差常住这家，一直很稳定"],
        "bad": ["整体一般，达不到预期"],
    },
}
GOOD_WORDS = [w for v in CAT_WORDS.values() for w in v["good"]]
BAD_WORDS = [w for v in CAT_WORDS.values() for w in v["bad"]]

COMPLAINT_STATUS = [("待处理", 20), ("处理中", 30), ("已闭环", 50)]


# ------------------------------------------------------------
# 5. 逐日生成预订/入住/餐饮/支付/服务/评价
# ------------------------------------------------------------
def build_daily(guests, hotel_room_types, hotel_rests, hotel_emps):
    reservation_id = 1
    stay_id = 1
    payment_id = 1
    meal_order_id = 1
    svc_order_id = 1
    record_id = 1
    review_id = 1

    guest_stats = {g[0]: g for g in guests}   # gid -> guest row
    active_ids = []                            # 有过入住的客户

    day_count = (END - START).days
    for di in range(day_count):
        d = START + timedelta(days=di)

        for (hid, _n, _c, _d, star, rooms, _f, _o, base_occ) in HOTELS:
            occ = occ_for_hotel(hid, d, base_occ)
            n_arrivals = max(0, round(rooms * occ * 0.55))   # 每日新抵约占在住55%
            rtypes = hotel_room_types[hid]
            rtype_ids = [t[0] for t in rtypes]
            rtype_w = [t[3] for t in rtypes]
            rtype_map = {t[0]: t for t in rtypes}

            for _ in range(n_arrivals):
                # 渠道
                cid = weighted([(c[0], c[4]) for c in CHANNELS])
                cinfo = next(c for c in CHANNELS if c[0] == cid)
                cancel_rate = cinfo[5]

                # 房型
                tot_w = sum(rtype_w)
                pick = weighted([(i, w) for i, w in enumerate(rtype_w)])
                rt = rtypes[pick]
                rt_id_, rt_name, std_price, _cnt = rt

                # 间夜
                nights = weighted(NIGHT_WEIGHTS)
                check_in = d
                check_out = d + timedelta(days=nights)

                # 预订时间
                lead = LEAD_DAYS[cid]
                if lead == 0:
                    lead_days = 0
                else:
                    lead_days = random.randint(lead[0], lead[1])
                book_dt = datetime.combine(d, time(14, 0)) - timedelta(days=lead_days)
                book_dt = book_dt.replace(
                    hour=random.randint(8, 23), minute=random.randint(0, 59))
                if book_dt < datetime.combine(START, time(0, 0)):
                    book_dt = datetime.combine(START, time(8, 0))

                # 价格：门市价 × 渠道系数 × 季节
                price_k = CH_PRICE_K[cid] * (
                    1.08 if seasonal_factor(d) > 1.0 else 0.95)
                booked_price = round(std_price * price_k *
                                     random.uniform(0.92, 1.06), 2)
                total_amount = round(booked_price * nights, 2)

                # 客户：62% 回头客（按入住次数加权），38% 任意客户
                if active_ids and random.random() < 0.62:
                    gid = random.choice(active_ids)
                else:
                    gid = random.randint(1, 40000)
                g = guest_stats[gid]
                if g[4] and g[4] > check_in:
                    pass  # 注册晚于入住也允许（散客现场注册口径），不做强制

                cancel = random.random() < cancel_rate
                if cancel:
                    cancel_dt = book_dt + timedelta(
                        hours=random.randint(1, max(1,
                            int((datetime.combine(check_in, time(18, 0)) - book_dt
                                 ).total_seconds() / 3600) or 1)))
                    if cancel_dt > datetime.combine(check_in, time(18, 0)):
                        cancel_dt = datetime.combine(check_in, time(11, 0))
                    add("reservation", (reservation_id, hid, rt_id_, gid, cid,
                                        book_dt, check_in, check_out, nights, 1,
                                        booked_price, total_amount, "已取消",
                                        cancel_dt))
                    reservation_id += 1
                    continue

                # NoShow 3%（不生成 stay_record）
                if random.random() < 0.03:
                    add("reservation", (reservation_id, hid, rt_id_, gid, cid,
                                        book_dt, check_in, check_out, nights, 1,
                                        booked_price, total_amount, "未入住", None))
                    reservation_id += 1
                    continue

                # 实际入住
                ci_dt = datetime.combine(check_in, time(14, random.randint(0, 59)))
                co_dt = datetime.combine(check_out, time(12, 0))
                status = "已入住" if check_out > END else "已完成"
                add("reservation", (reservation_id, hid, rt_id_, gid, cid,
                                    book_dt, check_in, check_out, nights, 1,
                                    booked_price, total_amount, status, None))

                add("stay_record", (stay_id, reservation_id, hid, rt_id_, gid,
                                    ci_dt, co_dt if check_out <= END else None,
                                    nights,
                                    1 if random.random() < 0.8 else 2,
                                    random.choice([0, 0, 0, 1, 2]),
                                    total_amount))

                # 房费收款
                pay_dt = (ci_dt if random.random() < 0.6
                          else co_dt - timedelta(hours=random.randint(1, 4)))
                if check_out > END:
                    pay_dt = min(pay_dt, datetime.combine(END, time(20, 0)))
                method = weighted(PAY_METHODS)
                add("payment", (payment_id, hid, gid, "房费", reservation_id,
                                pay_dt, total_amount, method, "已支付"))
                payment_id += 1

                # 客户统计
                if gid not in active_ids:
                    active_ids.append(gid)
                g[6] += nights
                g[7] = round(g[7] + total_amount, 2)
                g[8] += 1
                if g[9] is None or check_in > g[9]:
                    g[9] = check_in

                # ---- 餐饮 ----
                rests = hotel_rests[hid]
                buffet = next(r for r in rests if r[1] == "自助早餐厅")
                diners = 1 + (1 if random.random() < 0.25 else 0)
                # 每间夜 1 份免费早餐（不含早渠道除外——简化为都含）
                for ni in range(nights):
                    bm = d + timedelta(days=ni)
                    if bm >= END:
                        break
                    add("meal_order", (meal_order_id, buffet[0], hid, gid, None,
                                       diners, datetime.combine(bm, time(7, 30)),
                                       0.00, "早餐", "免单"))
                    meal_order_id += 1

                # 午/晚餐付费：每间夜 35% 概率一单
                for ni in range(nights):
                    md = d + timedelta(days=ni)
                    if md >= END:
                        break
                    if random.random() < 0.35 and len(rests) > 1:
                        zhongcan = next(r for r in rests if r[1] == "云栖中餐厅")
                        meal_type = random.choice(["午餐", "晚餐"])
                        mt_hour = 12 if meal_type == "午餐" else 18
                        amount = round(random.uniform(60, 260) * diners, 2)
                        mt_dt = datetime.combine(
                            md, time(mt_hour, random.randint(0, 50)))
                        add("meal_order", (meal_order_id, zhongcan[0], hid, gid,
                                           None, diners, mt_dt, amount,
                                           meal_type, "挂房账"))
                        add("payment", (payment_id, hid, gid, "餐饮",
                                        meal_order_id, mt_dt, amount,
                                        method if method != "现金" else "微信",
                                        "已支付"))
                        meal_order_id += 1
                        payment_id += 1

                # ---- 增值服务 12% ----
                if random.random() < 0.12:
                    sname, (lo, hi) = random.choice(SVC_ITEMS)
                    qty = 1
                    svc_dt = datetime.combine(d, time(random.randint(10, 21),
                                                      random.randint(0, 59)))
                    amt = round(random.uniform(lo, hi) * (
                        2 if sname in ("迷你吧", "洗衣") else 1), 2)
                    add("service_order", (svc_order_id, hid, gid, reservation_id,
                                          sname, svc_dt, qty, amt, "已完成"))
                    add("payment", (payment_id, hid, gid, "增值服务",
                                    svc_order_id, svc_dt, amt,
                                    weighted(PAY_METHODS), "已支付"))
                    svc_order_id += 1
                    payment_id += 1

                # ---- 服务记录：每笔入住 1 条客房清洁 + 25% 额外对客服务 ----
                emps = hotel_emps[hid]
                housekeeps = [e for e in emps if e[3] in ("客房服务员", "保洁")]
                if housekeeps:
                    emp = random.choice(housekeeps)
                    add("service_record", (record_id, hid, emp[0], gid,
                                           "客房清洁",
                                           datetime.combine(d, time(10, 0)),
                                           "完成", None))
                    record_id += 1
                if random.random() < 0.25:
                    stype = random.choice(["开夜床", "行李", "叫醒", "报修处理",
                                           "迎宾"])
                    pool = [e for e in emps if
                            (stype in ("行李", "叫醒", "迎宾") and e[3] in ("前台", "礼宾"))
                            or (stype == "报修处理" and e[3] == "工程维修")
                            or (stype == "开夜床" and e[3] in ("客房服务员", "保洁"))]
                    emp = random.choice(pool) if pool else random.choice(emps)
                    add("service_record", (record_id, hid, emp[0], gid, stype,
                                           datetime.combine(
                                               d, time(random.randint(9, 21),
                                                       random.randint(0, 59))),
                                           "完成", None))
                    record_id += 1

                # ---- 评价投诉：已完成离店 38% ----
                if check_out <= END and random.random() < 0.38:
                    roll = random.random()
                    if roll < 0.68:
                        rtype_word, rating = "好评", weighted(
                            [(5, 80), (4, 20)])
                        cat = random.choice(REVIEW_CATS + ["整体"])
                        content = random.choice(CAT_WORDS[cat]["good"])
                    elif roll < 0.86:
                        rtype_word, rating = "中评", 3
                        cat = random.choice(REVIEW_CATS)
                        content = ("整体还行，" + random.choice(CAT_WORDS[cat]["bad"])
                                   + "，希望改进")
                    else:
                        rtype_word, rating = "差评", random.choice([1, 2])
                        cat = random.choice(["卫生", "设施", "噪音", "服务", "早餐"])
                        content = random.choice(CAT_WORDS[cat]["bad"])
                    rt_dt = datetime.combine(check_out, time(20, 0)) + timedelta(
                        days=random.randint(1, 4))
                    if rt_dt > datetime.combine(END, time(23, 0)):
                        rt_dt = datetime.combine(END - timedelta(days=1), time(20, 0))
                    add("review_complaint", (review_id, hid, gid, reservation_id,
                                             cid, rtype_word, rating, cat,
                                             content, rt_dt,
                                             "已闭环" if rtype_word == "好评"
                                             else weighted(COMPLAINT_STATUS)))
                    review_id += 1

                stay_id += 1
                reservation_id += 1

            # 散客餐饮（午/晚餐各少量，非住客）
            if di % 2 == 0:
                rests = hotel_rests[hid]
                zhongcan = next((r for r in rests if r[1] == "云栖中餐厅"), None)
                if zhongcan:
                    for meal_type, hh in (("午餐", 12), ("晚餐", 18)):
                        for _ in range(random.randint(1, 3)):
                            diners = random.randint(1, 4)
                            amount = round(random.uniform(50, 220) * diners, 2)
                            mt_dt = datetime.combine(
                                d, time(hh, random.randint(5, 55)))
                            add("meal_order", (meal_order_id, zhongcan[0], hid,
                                               None, None, diners, mt_dt, amount,
                                               meal_type, "已支付"))
                            add("payment", (payment_id, hid, None, "餐饮",
                                            meal_order_id, mt_dt, amount,
                                            weighted(PAY_METHODS), "已支付"))
                            meal_order_id += 1
                            payment_id += 1


# ------------------------------------------------------------
# 6. expense 月度成本（明细生成后用聚合结果算 OTA 佣金，更真实）
# ------------------------------------------------------------
def build_expenses(cur):
    expense_id = 1
    months = []
    y, m = START.year, START.month
    # 只造完整月份的成本：END 是不含边界（2027-08-01），2027-08 只有 0 天业务，跳过
    while (y, m) < (END.year, END.month):
        months.append((y, m))
        m += 1
        if m == 13:
            y, m = y + 1, 1

    for (hid, _n, _c, _d, star, rooms, _f, _o, _b) in HOTELS:
        # 当月实际房费收入 & OTA 房费
        cur.execute("""
            SELECT DATE_FORMAT(pay_time,'%%Y-%%m') AS ym,
                   SUM(amount) AS room_rev
            FROM payment
            WHERE hotel_id=%s AND biz_type='房费' AND pay_status='已支付'
            GROUP BY ym
        """, (hid,))
        room_by_month = {r["ym"]: float(r["room_rev"] or 0) for r in cur.fetchall()}

        cur.execute("""
            SELECT DATE_FORMAT(p.pay_time,'%%Y-%%m') AS ym,
                   SUM(p.amount) AS ota_rev
            FROM payment p
            JOIN reservation r ON r.reservation_id = p.biz_id
            JOIN channel c ON c.channel_id = r.channel_id
            WHERE p.hotel_id=%s AND p.biz_type='房费'
              AND p.pay_status='已支付' AND c.channel_type='OTA'
            GROUP BY ym
        """, (hid,))
        ota_by_month = {r["ym"]: float(r["ota_rev"] or 0) for r in cur.fetchall()}

        cur.execute("""
            SELECT COUNT(*) AS n FROM employee
            WHERE hotel_id=%s AND employee_status='在职'
        """, (hid,))
        emp_n = cur.fetchone()["n"]

        rent_m = round(rooms * {3: 260, 4: 450, 5: 700}[star] * 0.9, 0)
        salary_m = round(emp_n * {3: 5200, 4: 6800, 5: 8800}[star], 0)

        for (y, mth) in months:
            ym = f"{y}-{mth:02d}"
            first = date(y, mth, 1)
            room_rev = room_by_month.get(ym, 0)
            items = [
                ("租金", rent_m, "月度物业租金"),
                ("人力", salary_m, "员工工资社保"),
                ("水电", round(rooms * {3: 90, 4: 140, 5: 200}[star]
                               * random.uniform(0.85, 1.2), 0), "水电费"),
                ("能耗", round(rooms * {3: 60, 4: 90, 5: 130}[star]
                               * random.uniform(0.8, 1.25), 0), "燃气/空调能耗"),
                ("物料", round(max(room_rev, 1) * 0.05, 0), "客房耗材/布草洗涤"),
                ("维修", round(rooms * random.uniform(40, 130), 0), "设施维修保养"),
                ("营销", round(max(room_rev, 1) * 0.03, 0), "推广/会员活动"),
                ("折旧", round(rooms * {3: 180, 4: 260, 5: 360}[star], 0),
                 "固定资产折旧"),
                ("OTA佣金", round(ota_by_month.get(ym, 0) * 0.13, 0),
                 "OTA 渠道佣金（按成交计提）"),
            ]
            for etype, amt, desc in items:
                add("expense", (expense_id, hid, first, etype, amt,
                                f"{mth}月{desc}"))
                expense_id += 1


# ------------------------------------------------------------
# 7. user_info 认证账号：在职员工全员（初始密码 123456，PBKDF2 每人独立盐）
#    格式 pbkdf2_sha256$迭代数$盐hex$哈希hex——与 app/api/auth 的校验函数一致
# ------------------------------------------------------------
def _hash_password(pwd: str, iterations: int = 100_000) -> str:
    salt = os.urandom(16)
    dk = hashlib.pbkdf2_hmac("sha256", pwd.encode("utf-8"), salt, iterations)
    return f"pbkdf2_sha256${iterations}${salt.hex()}${dk.hex()}"


def build_accounts(active_codes):
    for code in active_codes:
        add("user_info", (code, _hash_password("123456")))


# ------------------------------------------------------------
# 主流程
# ------------------------------------------------------------
def main():
    print("连接 MySQL ...")
    conn = pymysql.connect(**DB_CONFIG, autocommit=False,
                           cursorclass=pymysql.cursors.DictCursor)
    try:
        with conn.cursor() as cur:
            print("重建表结构（执行 database/schema.sql，DROP+CREATE 17 张表）...")
            schema = (Path(__file__).resolve().parent / "schema.sql").read_text(encoding="utf-8")
            for stmt in schema.split(";"):
                s = stmt.strip()
                if s:
                    cur.execute(s)
            cur.execute("USE `hotel`")

            print("生成基础档案 ...")
            hotel_room_types, hotel_rests = build_base()
            print("生成客户池 40000 ...")
            guests = build_guests()
            print("生成业务员工（编号+级别+邮箱）与认证账号 ...")
            hotel_emps, active_codes = build_employees()
            build_accounts(active_codes)
            total0 = flush_all(cur)
            conn.commit()
            print(f"  已插入基础数据 {total0} 行")

            print(f"逐日生成预订/入住/餐饮/服务/评价（{(END - START).days} 天 × 10 店）...")
            build_daily(guests, hotel_room_types, hotel_rests, hotel_emps)
            total1 = flush_all(cur)
            conn.commit()
            print(f"  已插入业务明细 {total1} 行")

            print("回写客户汇总（间夜/消费/次数/会员等级）...")
            # 用 stay 期间累计值更新 guest（guest 行对象里已统计）
            g_rows = []
            for g in guests:
                if g[8] == 0:
                    continue
                spent = g[7]
                if spent >= 50000:
                    level = "钻石"
                elif spent >= 20000:
                    level = "铂金"
                elif spent >= 8000:
                    level = "金卡"
                elif spent >= 3000:
                    level = "银卡"
                else:
                    level = g[5]
                g_rows.append((g[6], spent, g[8], g[9], level, g[0]))
            up_sql = ("UPDATE guest SET total_stay_nights=%s,total_spent=%s,"
                      "stay_count=%s,last_stay_date=%s,member_level=%s "
                      "WHERE guest_id=%s")
            for i in range(0, len(g_rows), 1000):
                cur.executemany(up_sql, g_rows[i:i + 1000])
            conn.commit()

            print("生成月度成本支出 ...")
            build_expenses(cur)
            total2 = flush_all(cur)
            conn.commit()
            print(f"  已插入成本记录 {total2} 行")

            # --------------------------------------------------
            # 校验
            # --------------------------------------------------
            print("\n========== 数据校验 ==========")
            for t in ALL_TABLES:
                cur.execute(f"SELECT COUNT(*) AS n FROM `{t}`")
                print(f"  {t:22s} {cur.fetchone()['n']:>10,}")

            # 校验用最后一个完整月（END 是不含边界，最后一个完整月=2027-07）
            last_full = (END - timedelta(days=1)).replace(day=1)
            month_end = END
            print(f"\n--- {last_full:%Y年%m月} 各店经营概览（OCC / ADR / RevPAR / 营收）---")
            cur.execute(f"""
                SELECT h.hotel_name,
                       ROUND(SUM(s.nights) /
                             (h.room_count * DAY(LAST_DAY('{last_full}'))) * 100, 1) AS occ_pct,
                       ROUND(SUM(s.room_amount) / NULLIF(SUM(s.nights), 0), 0) AS adr,
                       ROUND(SUM(s.room_amount) / (h.room_count * DAY(LAST_DAY('{last_full}'))), 0) AS revpar,
                       ROUND(SUM(s.room_amount), 0) AS room_rev
                FROM stay_record s
                JOIN hotel h ON h.hotel_id = s.hotel_id
                WHERE s.actual_check_in >= '{last_full}'
                  AND s.actual_check_in <  '{month_end}'
                GROUP BY h.hotel_id
                ORDER BY h.hotel_id
            """)
            for r in cur.fetchall():
                print(f"  {r['hotel_name']:<32s} OCC={r['occ_pct']}%  "
                      f"ADR={r['adr']}  RevPAR={r['revpar']}  "
                      f"房费收入={r['room_rev']:,}")

            print(f"\n--- {last_full:%Y年%m月} 投诉未闭环清单（前5条）---")
            cur.execute(f"""
                SELECT h.hotel_name, rc.category, rc.content
                FROM review_complaint rc JOIN hotel h ON h.hotel_id=rc.hotel_id
                WHERE rc.review_type IN ('差评','投诉')
                  AND rc.handle_status <> '已闭环'
                  AND rc.review_time >= '{last_full}'
                LIMIT 5
            """)
            rows = cur.fetchall()
            if not rows:
                print("  （无未闭环投诉）")
            for r in rows:
                print(f"  [{r['hotel_name']}] {r['category']}：{r['content']}")

        print("\n种子数据生成完成 ✅")
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
