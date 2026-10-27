-- ============================================================
-- 43号 数据分析平台 · 数据库扩展脚本 v2（v1.3 配套）
-- 库名：agent（对应 .env 的 MYSQL_DATABASE）
-- 用途：
--   1) 删掉 v1.2 留下的 user_login_log / user_behavior_log（看板/登录都不做了）
--   2) notification_record 扩 2 个字段（trigger_source / triggered_by）
--   3) 4 张运营扩展表 DDL 已合并进 schema.sql，本脚本不重复（保证单一来源）
--
-- 业务表 + 4 张新表（共 11 张）→ 跑 schema.sql
-- 本脚本（schema_extension_v2.sql）只做清理 + notification_record 扩展
--
-- 执行：mysql -uroot -p123456 agent < schema_extension_v2.sql
-- ============================================================

USE `agent`;

-- ------------------------------------------------------------
-- 1. 删 v1.2 废弃的 2 张表
-- ------------------------------------------------------------
DROP TABLE IF EXISTS `user_login_log`;
DROP TABLE IF EXISTS `user_behavior_log`;

-- ------------------------------------------------------------
-- 2. notification_record 扩字段（仅在表存在时执行）
-- ------------------------------------------------------------
-- 原 schema:
--   id / user_id / to_email / notification_type / subject / content /
--   send_status / send_time / error_msg
-- v1.3 新增：
--   trigger_source   — 区分"谁触发发的"：system_agent / manual / scheduled / verify_code
--   triggered_by     — 触发人 user_info.id（system_agent 自动发时为调 SystemAgent 的那个用户）
-- ------------------------------------------------------------
SET @tbl_exists = (SELECT COUNT(*) FROM information_schema.tables
                   WHERE table_schema = DATABASE() AND table_name = 'notification_record');

SET @col_exists = (
    SELECT COUNT(*) FROM information_schema.columns
    WHERE table_schema = DATABASE()
      AND table_name = 'notification_record'
      AND column_name = 'trigger_source'
);
SET @sql = IF(
    @tbl_exists = 0,
    'SELECT ''notification_record 不存在，跳过 trigger_source'' AS info',
    IF(
        @col_exists = 0,
        'ALTER TABLE `notification_record` ADD COLUMN `trigger_source` VARCHAR(32) DEFAULT ''manual'' COMMENT ''触发来源：system_agent/manual/scheduled/verify_code'' AFTER `notification_type`',
        'SELECT ''trigger_source 已存在，跳过'' AS info'
    )
);
PREPARE stmt FROM @sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

SET @col_exists = (
    SELECT COUNT(*) FROM information_schema.columns
    WHERE table_schema = DATABASE()
      AND table_name = 'notification_record'
      AND column_name = 'triggered_by'
);
SET @sql = IF(
    @tbl_exists = 0,
    'SELECT ''notification_record 不存在，跳过 triggered_by'' AS info',
    IF(
        @col_exists = 0,
        'ALTER TABLE `notification_record` ADD COLUMN `triggered_by` INT DEFAULT NULL COMMENT ''触发人 user_info.id（system_agent 自动发时记录操作人）'' AFTER `trigger_source`,
         ADD KEY `idx_trigger_source` (`trigger_source`),
         ADD KEY `idx_triggered_by` (`triggered_by`)',
        'SELECT ''triggered_by 已存在，跳过'' AS info'
    )
);
PREPARE stmt FROM @sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

-- ------------------------------------------------------------
-- 3. 验证：表清单 + notification_record 表结构（用 IF 容错，未建时跳过）
-- ------------------------------------------------------------
SELECT '==== 表清单（11 张） ====' AS step;
SHOW TABLES;

SELECT '==== notification_record 扩字段后（若不存在跳过） ====' AS step;
SET @tbl_exists = (SELECT COUNT(*) FROM information_schema.tables
                   WHERE table_schema = DATABASE() AND table_name = 'notification_record');
SET @sql = IF(@tbl_exists = 1, 'DESCRIBE `notification_record`', 'SELECT ''notification_record 不存在，跳过'' AS info');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SELECT '==== 各表行数（不存在则跳过） ====' AS step;
SELECT 'customer' AS tbl, COUNT(*) AS cnt FROM customer
UNION ALL SELECT 'customer_behavior', COUNT(*) FROM customer_behavior
UNION ALL SELECT 'orders', COUNT(*) FROM orders
UNION ALL SELECT 'products', COUNT(*) FROM products
UNION ALL SELECT 'sales', COUNT(*) FROM sales
UNION ALL SELECT 'user_info', COUNT(*) FROM user_info
UNION ALL SELECT 'coupon', COUNT(*) FROM coupon
UNION ALL SELECT 'customer_coupon', COUNT(*) FROM customer_coupon
UNION ALL SELECT 'monthly_sales', COUNT(*) FROM monthly_sales
UNION ALL SELECT 'category_target', COUNT(*) FROM category_target
UNION ALL SELECT 'notification_record', COUNT(*) FROM notification_record;

-- 废弃表已删（这俩如果还在会报错，正好兜底）
SELECT '==== 废弃表应已删除 ====' AS step;
SELECT IF(
    (SELECT COUNT(*) FROM information_schema.tables
     WHERE table_schema = DATABASE() AND table_name = 'user_login_log') = 0,
    '✓ user_login_log 已删除', '✗ user_login_log 还在！'
) AS check_login_log;
SELECT IF(
    (SELECT COUNT(*) FROM information_schema.tables
     WHERE table_schema = DATABASE() AND table_name = 'user_behavior_log') = 0,
    '✓ user_behavior_log 已删除', '✗ user_behavior_log 还在！'
) AS check_behavior_log;
