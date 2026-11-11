"""
病历时效质控独立包（主设计文档 §15，方案 A / 决策 D1）。

本包只承载病历时效质控能力，与既有 Dify 事后质控链路、双调度器、
prearchive_service 及 app/emr_vastbase_client.py 完全隔离；核心红线见
开发起步包/05_病历时效质控设计指针.md §3（生产库默认只读、禁明文口令、
ADM_REC/CHIEF_FIRST_ROUND 禁 LOCK_EMR）。
"""
