-- =====================================================================
-- Oracle 人工审批 DDL 脚本：WP01 性能索引（064 总计划 WP01 任务 6）
-- 生成时间：2026-11-19 ｜ 生成者：WP01（ZCode / GLM-5.3-Flash）
-- 本文件只作为 DBA 审批与人工执行的素材，绝对不要由应用自动执行！
--
-- 用途：
--   1) 为 MED_PUSH_LOG（应用表名 push_log）建立 3 条复合索引，消除
--      总览/列表对 245,555 行 / 7.45 GB CLOB 大表的低效扫描；
--   2) DISCHARGE_DEPT 列由应用启动手工迁移自动添加（可空、无默认值，
--      Oracle 上是秒级元数据操作）——索引 IDX_PUSH_LOG_DISCHARGE_DEPT
--      依赖该列，必须在应用新版本启动一次之后再建。
--
-- 影响表：MED_PUSH_LOG（push_log）
-- 锁表评估：CREATE INDEX ... ONLINE 建索引不阻塞 DML（仅短暂字典锁），
--   建议低峰期执行；245k 行 ONLINE 建索引预计秒级~数十秒。
--
-- 执行前预检 SQL（逐条手工跑，确认当前状态）：
--   1) 列是否已存在（应用启动迁移后应已存在）：
--      SELECT COLUMN_NAME, DATA_TYPE, DATA_LENGTH, NULLABLE
--        FROM ALL_TAB_COLUMNS
--       WHERE OWNER = USER AND TABLE_NAME = 'MED_PUSH_LOG'
--         AND COLUMN_NAME = 'DISCHARGE_DEPT';
--   2) 现有索引：
--      SELECT INDEX_NAME, UNIQUENESS FROM ALL_INDEXES
--       WHERE OWNER = USER AND TABLE_NAME = 'MED_PUSH_LOG';
--   3) 当前 NULL 行数（回填前基线，预期 ≈245k）：
--      SELECT COUNT(*) FROM MED_PUSH_LOG WHERE DISCHARGE_DEPT IS NULL;
--
-- 部署顺序（严格按序）：
--   ① 发布 WP01 新代码（应用启动时自动补列 DISCHARGE_DEPT，SQLite/Oracle 兼容）；
--   ② 低峰期人工执行下方 3 条 CREATE INDEX ... ONLINE；
--   ③ 分批运行回填脚本（不产生本 SQL 的 dbms_lob 批量 JSON 解析）：
--        python scripts/backfill_pushlog_discharge_dept_20261119.py --apply --batch 2000
--   ④ 复核：SELECT COUNT(*) FROM MED_PUSH_LOG WHERE DISCHARGE_DEPT IS NULL;
--      （趋近 0 后，discharge_dept_name 筛选的 dbms_lob.instr CLOB 扫描自然消失）
--
-- =====================================================================

-- ---- 索引 1：日志列表/总览「当前结果 + 状态 + 有效契约 + 推送时间」组合查询 ----
CREATE INDEX IDX_PUSH_LOG_CURR_TIME
    ON MED_PUSH_LOG (SUPERSEDED_BY, STATUS, CONTRACT_VALID, PUSH_TIME DESC)
    ONLINE;

-- ---- 索引 2：严重度/科室分布（/stats/severity、/stats/anomaly-top、总览聚合）----
CREATE INDEX IDX_PUSH_LOG_CURR_SEV_DEPT
    ON MED_PUSH_LOG (SUPERSEDED_BY, STATUS, CONTRACT_VALID, SEVERITY, DEPT)
    ONLINE;

-- ---- 索引 3：出院科室筛选（依赖 DISCHARGE_DEPT 列已存在；见上方预检 1）----
CREATE INDEX IDX_PUSH_LOG_DISCHARGE_DEPT
    ON MED_PUSH_LOG (DISCHARGE_DEPT)
    ONLINE;

-- =====================================================================
-- 备用：若应用启动迁移因故未生效，可人工补列（二选一，勿重复执行，
--       重复执行报 ORA-01430: column being added already exists in table）。
--       列必须为「可空、无默认值」，避免 24.5 万行历史数据整表回写。
--
-- ALTER TABLE MED_PUSH_LOG ADD (DISCHARGE_DEPT VARCHAR2(120));
--
-- 历史行回填不要用 SQL 里 dbms_lob 批量解析 JSON，请使用应用侧分批脚本：
--   python scripts/backfill_pushlog_discharge_dept_20261119.py --apply --batch 2000
-- =====================================================================

-- ---- 完整回滚 SQL（索引可安全回滚；列保留不删——空列无害，删除列会连带丢数据）----
-- DROP INDEX IDX_PUSH_LOG_CURR_TIME;
-- DROP INDEX IDX_PUSH_LOG_CURR_SEV_DEPT;
-- DROP INDEX IDX_PUSH_LOG_DISCHARGE_DEPT;
