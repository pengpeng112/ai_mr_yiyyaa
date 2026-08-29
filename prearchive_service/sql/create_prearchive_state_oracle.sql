-- 031 T2-5：预检轮询状态表（Oracle 生产应用库，可选后端 service.state_backend=db）
-- 红线：本脚本随代码交付但【不自动执行】；由 DBA 按 023 §9.1 批准单流程手工执行。
-- 服务代码首用显式检查表存在，缺失即 StateStoreError——绝不自动建表（R14）。

CREATE TABLE MED_PREARCHIVE_STATE (
    ID           NUMBER(19)      NOT NULL,
    STATE_KEY    VARCHAR2(64)    DEFAULT 'default' NOT NULL,
    STATE_JSON   CLOB            NOT NULL,             -- {"watermark","last_processed","iterations"}
    UPDATED_AT   DATE            NOT NULL,
    CONSTRAINT PK_MED_PREARCHIVE_STATE PRIMARY KEY (ID),
    CONSTRAINT UQ_MED_PREARCHIVE_STATE_KEY UNIQUE (STATE_KEY)
);

CREATE INDEX IX_MED_PREARCHIVE_STATE_KEY ON MED_PREARCHIVE_STATE (STATE_KEY);

CREATE SEQUENCE SEQ_MED_PREARCHIVE_STATE START WITH 1 INCREMENT BY 1 NOCACHE;

COMMENT ON TABLE MED_PREARCHIVE_STATE IS '028/031 预检轮询状态（水位/检查键去重/迭代数；独立表）';
COMMENT ON COLUMN MED_PREARCHIVE_STATE.STATE_JSON IS '状态 JSON：watermark/last_processed{pid|vid:iso}/iterations';
