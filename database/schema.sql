-- ============================================================
-- 连锁酒店管理助手 · 数据库建表脚本（MySQL 5.7+/8.0）【2026-10-23 定稿】
-- 库名：hotel（对应 .env 的 MYSQL_DATABASE）
-- 用途：NL2SQL 智能体的业务数据源
--
-- 📋 表清单（物理 17 张 = 业务 15 + 留痕 1 + 认证 1）：
--   一、LLM 可查表 16 张：
--     1. hotel            酒店门店          2. room_type        房型
--     3. guest            客户/会员         4. reservation      预订订单
--     5. stay_record      入住记录          6. channel          销售渠道
--     7. payment          支付收入          8. expense          成本支出
--     9. restaurant       餐厅              10. meal_order      餐饮订单
--     11. menu_item       菜品              12. service_order   增值服务订单
--     13. employee        员工              14. service_record  服务记录
--     15. review_complaint 评价投诉         16. notification_record 邮件通知留痕
--   二、纯认证表 1 张（不进入 LLM 查询清单，防密码哈希被查）：
--     17. user_info       认证表（employee_id + password_hash）
--
-- 2026-10-23 定稿变更（员工编号登录改造）：
--   ① employee：employee_id 改为「员工编号即主键」（规则=入职年4+区域码2+部门码2+序号2，
--      如 2018000101；去自增），新增 email（收邮件用，UNIQUE 可空）、level（五级权限）
--   ② user_info：重建为纯认证表（employee_id + password_hash），撤出 LLM 查询清单
--   ③ notification_record：user_id 改名 employee_id（与 triggered_by 同指向 employee）
-- 码表：区域码 总部00/北京01/上海02/广州03/深圳04/成都05/杭州06/三亚07；
--       部门码 管理01/前厅02/客房03/餐饮04/工程05/安保06
-- ============================================================

CREATE DATABASE IF NOT EXISTS `hotel` DEFAULT CHARACTER SET utf8mb4;
USE `hotel`;

SET FOREIGN_KEY_CHECKS = 0;

-- ------------------------------------------------------------
-- 1. hotel 酒店门店表：每家门店一行
-- ------------------------------------------------------------
DROP TABLE IF EXISTS `hotel`;
CREATE TABLE `hotel` (
    `hotel_id`      INT          NOT NULL COMMENT '酒店ID（主键）',
    `hotel_name`    VARCHAR(64)  DEFAULT NULL COMMENT '酒店名称',
    `city`          VARCHAR(32)  DEFAULT NULL COMMENT '所在城市',
    `district`      VARCHAR(32)  DEFAULT NULL COMMENT '所在行政区',
    `star_level`    TINYINT      DEFAULT NULL COMMENT '星级 2-5',
    `room_count`    INT          DEFAULT NULL COMMENT '可售客房总数（间）',
    `floor_count`   INT          DEFAULT NULL COMMENT '楼层数',
    `open_date`     DATE         DEFAULT NULL COMMENT '开业日期',
    `hotel_status`  VARCHAR(16)  DEFAULT '营业中' COMMENT '营业状态：营业中/装修中/停业',
    PRIMARY KEY (`hotel_id`),
    KEY `idx_city` (`city`)                             -- 按城市聚合高频
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='酒店门店表';

-- ------------------------------------------------------------
-- 2. room_type 房型表：每家酒店的房型（酒店 × 房型，多行）
-- ------------------------------------------------------------
DROP TABLE IF EXISTS `room_type`;
CREATE TABLE `room_type` (
    `room_type_id`   INT          NOT NULL COMMENT '房型ID（主键）',
    `hotel_id`       INT          NOT NULL COMMENT '所属酒店ID',
    `room_type_name` VARCHAR(32)  DEFAULT NULL COMMENT '房型名称：大床房/双床房/套房/行政房...',
    `bed_type`       VARCHAR(16)  DEFAULT NULL COMMENT '床型：大床/双床/圆床/上下铺',
    `area_sqm`       INT          DEFAULT NULL COMMENT '房间面积（平方米）',
    `standard_price` DECIMAL(10,2) DEFAULT NULL COMMENT '门市价/标准房价（元）',
    `room_count`     INT          DEFAULT NULL COMMENT '该房型房间数（间）',
    `floor_no`       VARCHAR(32)  DEFAULT NULL COMMENT '所在楼层',
    PRIMARY KEY (`room_type_id`),
    KEY `idx_hotel` (`hotel_id`)                        -- 按酒店查房型高频
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='房型表';

-- ------------------------------------------------------------
-- 3. guest 客户/会员表：每个客户一行档案
-- ------------------------------------------------------------
DROP TABLE IF EXISTS `guest`;
CREATE TABLE `guest` (
    `guest_id`         INT          NOT NULL COMMENT '客户ID（主键）',
    `guest_name`       VARCHAR(64)  DEFAULT NULL COMMENT '客户姓名',
    `phone`            VARCHAR(20)  DEFAULT NULL COMMENT '手机号',
    `gender`           VARCHAR(8)   DEFAULT NULL COMMENT '性别',
    `register_date`    DATE         DEFAULT NULL COMMENT '注册/首住日期',
    `member_level`     VARCHAR(16)  DEFAULT '普通' COMMENT '会员等级：普通/银卡/金卡/铂金/钻石',
    `total_stay_nights` INT         DEFAULT 0 COMMENT '累计入住间夜数（预汇总）',
    `total_spent`      DECIMAL(12,2) DEFAULT 0 COMMENT '累计消费金额（预汇总）',
    `stay_count`       INT          DEFAULT 0 COMMENT '累计入住次数（预汇总）',
    `last_stay_date`   DATE         DEFAULT NULL COMMENT '最近一次入住日期（流失判断用）',
    `preference`       VARCHAR(128) DEFAULT NULL COMMENT '入住偏好（无烟/高楼层/双床...）',
    PRIMARY KEY (`guest_id`),
    KEY `idx_member_level` (`member_level`),            -- 会员分群高频
    KEY `idx_last_stay` (`last_stay_date`)              -- 流失召回高频
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='客户/会员表';

-- ------------------------------------------------------------
-- 4. reservation 预订订单表：每行一笔预订
-- ------------------------------------------------------------
DROP TABLE IF EXISTS `reservation`;
CREATE TABLE `reservation` (
    `reservation_id` INT          NOT NULL COMMENT '预订ID（主键）',
    `hotel_id`       INT          NOT NULL COMMENT '酒店ID',
    `room_type_id`   INT          NOT NULL COMMENT '房型ID',
    `guest_id`       INT          DEFAULT NULL COMMENT '客户ID（散客可为空）',
    `channel_id`     INT          DEFAULT NULL COMMENT '预订渠道ID',
    `book_date`      DATETIME     DEFAULT NULL COMMENT '下单/预订时间',
    `check_in_date`  DATE         DEFAULT NULL COMMENT '预计入住日期',
    `check_out_date` DATE         DEFAULT NULL COMMENT '预计离店日期',
    `nights`         INT          DEFAULT NULL COMMENT '预订间夜数',
    `room_count`     INT          DEFAULT 1 COMMENT '预订房间数',
    `booked_price`   DECIMAL(10,2) DEFAULT NULL COMMENT '预订成交单价（元/间夜）',
    `total_amount`   DECIMAL(12,2) DEFAULT NULL COMMENT '订单总金额（房费）',
    `order_status`   VARCHAR(16)  DEFAULT NULL COMMENT '状态：已入住/已完成/已取消/未入住',
    `cancel_date`    DATETIME     DEFAULT NULL COMMENT '取消时间（未取消为 NULL）',
    PRIMARY KEY (`reservation_id`),
    KEY `idx_hotel_date` (`hotel_id`, `check_in_date`), -- 按店按日查入住高频
    KEY `idx_status` (`order_status`),                  -- 状态过滤高频
    KEY `idx_guest` (`guest_id`),                       -- 客户复住分析高频
    KEY `idx_channel` (`channel_id`)                    -- 渠道分析高频
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='预订订单表';

-- ------------------------------------------------------------
-- 5. stay_record 入住记录（夜态表）：每笔实际入住一行
--    预订 ≠ 实际入住（有取消/NoShow/换房/延退），核心指标以此表为准
-- ------------------------------------------------------------
DROP TABLE IF EXISTS `stay_record`;
CREATE TABLE `stay_record` (
    `stay_id`        INT          NOT NULL COMMENT '入住记录ID（主键）',
    `reservation_id` INT          DEFAULT NULL COMMENT '来源预订ID',
    `hotel_id`       INT          NOT NULL COMMENT '酒店ID',
    `room_type_id`   INT          NOT NULL COMMENT '实际入住房型ID',
    `guest_id`       INT          DEFAULT NULL COMMENT '客户ID',
    `actual_check_in`  DATETIME   DEFAULT NULL COMMENT '实际入住时间',
    `actual_check_out` DATETIME   DEFAULT NULL COMMENT '实际离店时间',
    `nights`         INT          DEFAULT NULL COMMENT '实际间夜数（OCC/间夜量口径）',
    `adults`         INT          DEFAULT 1 COMMENT '成人数',
    `children`       INT          DEFAULT 0 COMMENT '儿童数',
    `room_amount`    DECIMAL(12,2) DEFAULT NULL COMMENT '实际房费金额',
    PRIMARY KEY (`stay_id`),
    KEY `idx_hotel_ci` (`hotel_id`, `actual_check_in`), -- OCC/RevPAR 按店按日聚合高频
    KEY `idx_guest` (`guest_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='入住记录表';

-- ------------------------------------------------------------
-- 6. channel 销售渠道表
-- ------------------------------------------------------------
DROP TABLE IF EXISTS `channel`;
CREATE TABLE `channel` (
    `channel_id`   INT          NOT NULL COMMENT '渠道ID（主键）',
    `channel_name` VARCHAR(32)  DEFAULT NULL COMMENT '渠道名称：散客/会员直订/携程/美团/飞猪/企业协议...',
    `channel_type` VARCHAR(16)  DEFAULT NULL COMMENT '渠道类型：直销/OTA/协议/旅行社',
    `commission_rate` DECIMAL(5,2) DEFAULT 0 COMMENT '佣金率（百分比数值，如 15.00=15%）',
    PRIMARY KEY (`channel_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='销售渠道表';

-- ------------------------------------------------------------
-- 7. payment 支付收入表：每笔收款一行（房费/餐饮/增值服务统一在此）
-- ------------------------------------------------------------
DROP TABLE IF EXISTS `payment`;
CREATE TABLE `payment` (
    `payment_id`     INT          NOT NULL COMMENT '支付ID（主键）',
    `hotel_id`       INT          NOT NULL COMMENT '酒店ID',
    `guest_id`       INT          DEFAULT NULL COMMENT '客户ID',
    `biz_type`       VARCHAR(16)  DEFAULT NULL COMMENT '业务类型：房费/餐饮/增值服务',
    `biz_id`         INT          DEFAULT NULL COMMENT '业务单据ID（reservation/meal_order/service_order 的ID）',
    `pay_time`       DATETIME     DEFAULT NULL COMMENT '支付时间',
    `amount`         DECIMAL(12,2) DEFAULT NULL COMMENT '支付金额（含税）',
    `pay_method`     VARCHAR(16)  DEFAULT NULL COMMENT '支付方式：现金/微信/支付宝/银行卡/挂账',
    `pay_status`     VARCHAR(16)  DEFAULT NULL COMMENT '状态：已支付/已退款/部分退款',
    PRIMARY KEY (`payment_id`),
    KEY `idx_hotel_time` (`hotel_id`, `pay_time`),      -- 门店营收按时间聚合高频
    KEY `idx_biz` (`biz_type`, `biz_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='支付收入表';

-- ------------------------------------------------------------
-- 8. expense 成本支出表：每行一笔费用
-- ------------------------------------------------------------
DROP TABLE IF EXISTS `expense`;
CREATE TABLE `expense` (
    `expense_id`    INT          NOT NULL COMMENT '支出ID（主键）',
    `hotel_id`      INT          NOT NULL COMMENT '酒店ID',
    `expense_date`  DATE         DEFAULT NULL COMMENT '费用发生日期',
    `expense_type`  VARCHAR(32)  DEFAULT NULL COMMENT '费用类型：人力/水电/物料/能耗/维修/营销/租金/OTA佣金/折旧',
    `amount`        DECIMAL(12,2) DEFAULT NULL COMMENT '支出金额',
    `description`   VARCHAR(128) DEFAULT NULL COMMENT '费用说明',
    PRIMARY KEY (`expense_id`),
    KEY `idx_hotel_date` (`hotel_id`, `expense_date`),  -- 门店成本按月聚合高频
    KEY `idx_type` (`expense_type`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='成本支出表';

-- ------------------------------------------------------------
-- 9. restaurant 餐厅表：每家酒店可含多个餐厅
-- ------------------------------------------------------------
DROP TABLE IF EXISTS `restaurant`;
CREATE TABLE `restaurant` (
    `restaurant_id`   INT          NOT NULL COMMENT '餐厅ID（主键）',
    `hotel_id`        INT          NOT NULL COMMENT '所属酒店ID',
    `restaurant_name` VARCHAR(64)  DEFAULT NULL COMMENT '餐厅名称',
    `cuisine_type`    VARCHAR(32)  DEFAULT NULL COMMENT '菜系：中餐/西餐/自助/大堂吧/日料',
    `seat_count`      INT          DEFAULT NULL COMMENT '餐位数量',
    `meal_period`     VARCHAR(64)  DEFAULT NULL COMMENT '供餐时段：早餐/午餐/晚餐/夜宵',
    PRIMARY KEY (`restaurant_id`),
    KEY `idx_hotel` (`hotel_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='餐厅表';

-- ------------------------------------------------------------
-- 10. meal_order 餐饮订单表
-- ------------------------------------------------------------
DROP TABLE IF EXISTS `meal_order`;
CREATE TABLE `meal_order` (
    `meal_order_id` INT          NOT NULL COMMENT '餐饮订单ID（主键）',
    `restaurant_id` INT          NOT NULL COMMENT '餐厅ID',
    `hotel_id`      INT          NOT NULL COMMENT '酒店ID（冗余，方便按店汇总）',
    `guest_id`      INT          DEFAULT NULL COMMENT '客户ID',
    `menu_item_id`  INT          DEFAULT NULL COMMENT '主菜/菜品ID',
    `diner_count`   INT          DEFAULT 1 COMMENT '就餐人数（翻台率口径）',
    `meal_time`     DATETIME     DEFAULT NULL COMMENT '就餐/下单时间',
    `amount`        DECIMAL(12,2) DEFAULT NULL COMMENT '消费金额',
    `meal_type`     VARCHAR(16)  DEFAULT NULL COMMENT '餐段：早餐/午餐/晚餐/夜宵',
    `pay_status`    VARCHAR(16)  DEFAULT NULL COMMENT '支付状态：已支付/挂房账/免单',
    PRIMARY KEY (`meal_order_id`),
    KEY `idx_rest_time` (`restaurant_id`, `meal_time`), -- 餐厅营收/翻台率高频
    KEY `idx_hotel_time` (`hotel_id`, `meal_time`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='餐饮订单表';

-- ------------------------------------------------------------
-- 11. menu_item 菜品表
-- ------------------------------------------------------------
DROP TABLE IF EXISTS `menu_item`;
CREATE TABLE `menu_item` (
    `menu_item_id`   INT          NOT NULL COMMENT '菜品ID（主键）',
    `restaurant_id`  INT          NOT NULL COMMENT '所属餐厅ID',
    `dish_name`      VARCHAR(64)  DEFAULT NULL COMMENT '菜品名称',
    `category`       VARCHAR(32)  DEFAULT NULL COMMENT '分类：凉菜/热菜/主食/汤/甜点/酒水',
    `price`          DECIMAL(10,2) DEFAULT NULL COMMENT '单价',
    `cost`           DECIMAL(10,2) DEFAULT NULL COMMENT '成本（毛利用）',
    `on_sale`        TINYINT      DEFAULT 1 COMMENT '是否在售 0/1',
    PRIMARY KEY (`menu_item_id`),
    KEY `idx_rest` (`restaurant_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='菜品表';

-- ------------------------------------------------------------
-- 12. service_order 增值服务订单表（收费项：SPA/接送/洗衣/迷你吧/会议室）
--     注意与 service_record（员工对客服务记录）区分
-- ------------------------------------------------------------
DROP TABLE IF EXISTS `service_order`;
CREATE TABLE `service_order` (
    `service_order_id` INT          NOT NULL COMMENT '增值服务订单ID（主键）',
    `hotel_id`         INT          NOT NULL COMMENT '酒店ID',
    `guest_id`         INT          DEFAULT NULL COMMENT '客户ID',
    `reservation_id`   INT          DEFAULT NULL COMMENT '关联预订ID',
    `service_name`     VARCHAR(32)  DEFAULT NULL COMMENT '服务项目：SPA/接送机/洗衣/迷你吧/会议室/加床',
    `service_time`     DATETIME     DEFAULT NULL COMMENT '服务时间',
    `quantity`         INT          DEFAULT 1 COMMENT '数量',
    `amount`           DECIMAL(12,2) DEFAULT NULL COMMENT '收费金额',
    `order_status`     VARCHAR(16)  DEFAULT NULL COMMENT '状态：待服务/已完成/已取消',
    PRIMARY KEY (`service_order_id`),
    KEY `idx_hotel_time` (`hotel_id`, `service_time`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='增值服务订单表';

-- ------------------------------------------------------------
-- 13. employee 员工表（业务档案 + 收件人 + 级别）【2026-10-23 定稿改】
--     employee_id = 员工编号（去自增）：入职年(4)+区域码(2)+部门码(2)+序号(2)
-- ------------------------------------------------------------
DROP TABLE IF EXISTS `employee`;
CREATE TABLE `employee` (
    `employee_id`  INT          NOT NULL COMMENT '员工编号（主键）：入职年(4)+区域码(2)+部门码(2)+序号(2)，如 2018000101',
    `employee_name` VARCHAR(64) DEFAULT NULL COMMENT '员工姓名',
    `hotel_id`     INT          DEFAULT NULL COMMENT '所属酒店ID（总部人员为 NULL，区域码=00）',
    `position`     VARCHAR(32)  DEFAULT NULL COMMENT '职位：分公司老板/区域经理/店长/前厅经理/客房经理/餐饮经理/前台/礼宾/客房服务员/保洁/厨师/服务员/工程维修/安保',
    `department`   VARCHAR(32)  DEFAULT NULL COMMENT '部门：管理/前厅/客房/餐饮/工程/安保',
    `phone`        VARCHAR(20)  DEFAULT NULL COMMENT '联系电话',
    `hire_date`    DATE         DEFAULT NULL COMMENT '入职日期',
    `employee_status` VARCHAR(16) DEFAULT '在职' COMMENT '在职状态：在职/离职',
    `email`        VARCHAR(100) DEFAULT NULL COMMENT '收邮件用邮箱（员工自填可空，不是登录凭证）',
    `level`        TINYINT      NOT NULL DEFAULT 1 COMMENT '员工级别：1实习/见习 2正式员工 3经理 4老板 5管理员',
    PRIMARY KEY (`employee_id`),
    UNIQUE KEY `uk_employee_email` (`email`),           -- 邮箱唯一（两人不能绑同邮箱，NULL 不冲突）
    KEY `idx_hotel` (`hotel_id`),                       -- 按店查员工高频
    KEY `idx_position` (`position`)                     -- 按职位/收件人群发高频
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='员工表（业务档案+收件人+级别）';

-- ------------------------------------------------------------
-- 14. service_record 服务记录（客房/对客服务执行记录，非收费订单）
-- ------------------------------------------------------------
DROP TABLE IF EXISTS `service_record`;
CREATE TABLE `service_record` (
    `record_id`    INT          NOT NULL COMMENT '记录ID（主键）',
    `hotel_id`     INT          NOT NULL COMMENT '酒店ID',
    `employee_id`  INT          DEFAULT NULL COMMENT '提供服务的员工编号',
    `guest_id`     INT          DEFAULT NULL COMMENT '客户ID',
    `service_type` VARCHAR(32)  DEFAULT NULL COMMENT '服务类型：客房清洁/开夜床/行李/叫醒/报修处理/迎宾',
    `service_time` DATETIME     DEFAULT NULL COMMENT '服务时间',
    `result`       VARCHAR(16)  DEFAULT NULL COMMENT '结果：完成/未完成',
    `remark`       VARCHAR(128) DEFAULT NULL COMMENT '备注',
    PRIMARY KEY (`record_id`),
    KEY `idx_hotel_time` (`hotel_id`, `service_time`),
    KEY `idx_employee` (`employee_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='服务记录表';

-- ------------------------------------------------------------
-- 15. review_complaint 评价投诉表
-- ------------------------------------------------------------
DROP TABLE IF EXISTS `review_complaint`;
CREATE TABLE `review_complaint` (
    `review_id`     INT          NOT NULL COMMENT '评价ID（主键）',
    `hotel_id`      INT          NOT NULL COMMENT '酒店ID',
    `guest_id`      INT          DEFAULT NULL COMMENT '客户ID',
    `reservation_id` INT         DEFAULT NULL COMMENT '关联预订ID',
    `channel_id`    INT          DEFAULT NULL COMMENT '评价来源渠道ID',
    `review_type`   VARCHAR(16)  DEFAULT NULL COMMENT '类型：好评/中评/差评/投诉',
    `rating`        TINYINT      DEFAULT NULL COMMENT '评分 1-5',
    `category`      VARCHAR(32)  DEFAULT NULL COMMENT '问题类别：卫生/设施/服务/噪音/早餐/位置/性价比',
    `content`       VARCHAR(500) DEFAULT NULL COMMENT '评价/投诉内容',
    `review_time`   DATETIME     DEFAULT NULL COMMENT '评价时间',
    `handle_status` VARCHAR(16)  DEFAULT '待处理' COMMENT '处理状态：待处理/处理中/已闭环',
    PRIMARY KEY (`review_id`),
    KEY `idx_hotel_time` (`hotel_id`, `review_time`),
    KEY `idx_type` (`review_type`),
    KEY `idx_handle` (`handle_status`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='评价投诉表';

-- ------------------------------------------------------------
-- 16. notification_record 邮件通知留痕表（每次发信自动写入，可 SELECT）
--     【2026-10-23 定稿改】user_id → employee_id
-- ------------------------------------------------------------
DROP TABLE IF EXISTS `notification_record`;
CREATE TABLE `notification_record` (
    `id`                INT          NOT NULL AUTO_INCREMENT COMMENT '记录ID（主键）',
    `employee_id`       INT          DEFAULT NULL COMMENT '发件人员工编号（原 user_id）',
    `to_email`          VARCHAR(100) NOT NULL COMMENT '收件人邮箱',
    `notification_type` VARCHAR(50)  NOT NULL COMMENT '类型：verification/report/risk_alert/reminder',
    `trigger_source`    VARCHAR(32)  DEFAULT 'manual' COMMENT '触发来源：email_dispatcher/manual/verify_code',
    `triggered_by`      INT          DEFAULT NULL COMMENT '触发人员工编号',
    `subject`           VARCHAR(200) DEFAULT NULL COMMENT '邮件主题',
    `content`           TEXT         DEFAULT NULL COMMENT '邮件正文（关键内容摘要）',
    `send_status`       TINYINT      NOT NULL COMMENT '0=失败 1=成功',
    `send_time`         DATETIME     DEFAULT CURRENT_TIMESTAMP COMMENT '发送时间',
    `error_msg`         VARCHAR(200) DEFAULT NULL COMMENT '失败原因',
    PRIMARY KEY (`id`),
    KEY `idx_employee` (`employee_id`),
    KEY `idx_type` (`notification_type`),
    KEY `idx_time` (`send_time`),
    KEY `idx_trigger_source` (`trigger_source`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='邮件通知留痕表';

-- ------------------------------------------------------------
-- 17. user_info 纯认证表【2026-10-23 定稿重建】
--     只存密码哈希，不进入 LLM 查询清单——employee 可查，
--     密码若放 employee，LLM 一句话就能 SELECT 出哈希
-- ------------------------------------------------------------
DROP TABLE IF EXISTS `user_info`;
CREATE TABLE `user_info` (
    `employee_id`   INT          NOT NULL COMMENT '员工编号（登录名）',
    `password_hash` VARCHAR(255) NOT NULL COMMENT 'PBKDF2 密码哈希（初始密码 123456，员工可自改）',
    PRIMARY KEY (`employee_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='系统认证表（仅存密码哈希，禁止进入查询界面）';

SET FOREIGN_KEY_CHECKS = 1;

-- ============================================================
-- 面试可讲的索引设计要点：
--  1. stay_record 建 (hotel_id, actual_check_in) 联合索引：
--     OCC / RevPAR / 间夜量是最高频指标，按门店+入住日期聚合直接命中。
--  2. reservation 建 (hotel_id, check_in_date) 与 idx_status：
--     按店查当日在住/预抵、按状态过滤取消单，两个高频路径覆盖。
--  3. payment 建 (hotel_id, pay_time)：门店营收按月/按日聚合的主路径。
--  4. expense 建 (hotel_id, expense_date) + idx_type：
--     门店成本结构、GOP 毛利计算的过滤与分组都走索引。
--  5. meal_order 建 (restaurant_id, meal_time)：
--     餐厅营收与翻台率（按餐段去重桌/单）分析直接命中。
--  6. review_complaint 建 idx_type / idx_handle：
--     差评率、投诉闭环率按类型和处理状态聚合。
--  7. employee.email 唯一索引：两人不能绑同一邮箱，NULL 不冲突；
--     idx_position 支撑「SELECT email FROM employee WHERE position='店长'」群发。
--
-- 设计取舍：
--  - 业务员工(employee) 与 认证表(user_info) 分离：employee 是 LLM 可查的
--    业务档案（含邮箱/级别），密码哈希绝不能进可查表——user_info 只存
--    employee_id+password_hash 且从查询清单撤出，模型不知道有这张表。
--  - 预订(reservation) 与 实际入住(stay_record) 分离：存在取消/NoShow/换房/延退，
--    经营核心指标（OCC/ADR/RevPAR）一律以实际入住为准。
--  - 支付(payment) 与 各业务单据分离：房费/餐饮/增值服务统一收款口径，
--    biz_type+biz_id 多态关联，营收只看 pay_status='已支付'。
-- ============================================================
