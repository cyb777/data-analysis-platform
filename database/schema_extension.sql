-- ====================================================================
-- ⚠️  v1.3 起本脚本已废弃
--     - 看板功能砍了 → user_behavior_log 不做
--     - 登录功能拆出去独立项目 → user_login_log 不做
--     - 通知记录扩展（trigger_source / triggered_by）→ 改用 schema_extension_v2.sql
--     - 4 张新表 DDL → 已合并进 schema.sql
--
-- 43号 数据分析平台 · 数据库扩展脚本 v1.2（已废弃，仅留作历史）
-- 目的：支持登录鉴权 + 个人看板 + 数据导出 + 通知记录
-- 说明：不做 IP 定位 / 设备指纹 / 风控（已砍）
-- 执行：❌ 不再执行
-- ====================================================================

-- 1. user_info 不动（已够用，不 ALTER）

-- 2. user_login_log 登录日志（精简版：去掉 IP/UA/设备）
CREATE TABLE IF NOT EXISTS user_login_log (
    id INT AUTO_INCREMENT PRIMARY KEY,
    user_id INT NOT NULL                                                 COMMENT 'user_info.id',
    email VARCHAR(100) NOT NULL,
    login_time DATETIME DEFAULT CURRENT_TIMESTAMP,
    login_status TINYINT NOT NULL                                        COMMENT '0=失败 1=成功',
    fail_reason VARCHAR(100)                                             COMMENT '验证码错/账号锁定/邮箱不存在',
    INDEX idx_user_time (user_id, login_time),
    INDEX idx_email (email),
    INDEX idx_status (login_status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='用户登录日志（精简版）';

-- 3. user_behavior_log 用户行为日志（看板要用）
CREATE TABLE IF NOT EXISTS user_behavior_log (
    id INT AUTO_INCREMENT PRIMARY KEY,
    user_id INT NOT NULL,
    email VARCHAR(100) NOT NULL,
    action_type VARCHAR(50) NOT NULL                                     COMMENT 'login/send_code/verify/chat/export',
    action_detail TEXT                                                   COMMENT 'JSON存详情：问题/导出格式/分支',
    action_time DATETIME DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_user_time (user_id, action_time),
    INDEX idx_action_type (action_type),
    INDEX idx_email (email)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='用户行为日志（看板用）';

-- 4. notification_record 通知发送记录
CREATE TABLE IF NOT EXISTS notification_record (
    id INT AUTO_INCREMENT PRIMARY KEY,
    user_id INT                                                          COMMENT 'user_info.id（系统用户）',
    to_email VARCHAR(100) NOT NULL,
    notification_type VARCHAR(50) NOT NULL                               COMMENT 'verification/welcome/risk_alert/report/promotion',
    subject VARCHAR(200),
    content TEXT,
    send_status TINYINT NOT NULL                                         COMMENT '0=失败 1=成功',
    send_time DATETIME DEFAULT CURRENT_TIMESTAMP,
    error_msg VARCHAR(200),
    INDEX idx_user (user_id),
    INDEX idx_type (notification_type),
    INDEX idx_time (send_time)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='通知发送记录';

-- 5. 验证
SELECT 'user_info' AS tbl, COUNT(*) AS cnt FROM user_info
UNION ALL SELECT 'user_login_log', COUNT(*) FROM user_login_log
UNION ALL SELECT 'user_behavior_log', COUNT(*) FROM user_behavior_log
UNION ALL SELECT 'notification_record', COUNT(*) FROM notification_record;
