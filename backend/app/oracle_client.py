"""
Oracle 数据库连接与查询模块
"""
import logging
import time
from typing import List, Optional

logger = logging.getLogger(__name__)

# 尝试导入 cx_Oracle，开发环境可能未安装
try:
    import cx_Oracle
    HAS_CX_ORACLE = True
except ImportError:
    HAS_CX_ORACLE = False
    logger.warning("cx_Oracle 未安装，Oracle 查询功能不可用（开发环境可忽略）")


def get_oracle_connection(config: dict):
    """创建 Oracle 数据库连接"""
    if not HAS_CX_ORACLE:
        raise RuntimeError("cx_Oracle 未安装，请安装 cx_Oracle 和 Oracle Instant Client")

    dsn = cx_Oracle.makedsn(
        config["host"],
        config["port"],
        service_name=config["service_name"],
    )
    conn = cx_Oracle.connect(
        user=config["username"],
        password=config["password"],
        dsn=dsn,
        encoding="UTF-8",
    )
    return conn


def test_oracle_connection(config: dict) -> dict:
    """测试 Oracle 连接，返回延迟"""
    start = time.time()
    try:
        conn = get_oracle_connection(config)
        cursor = conn.cursor()
        cursor.execute("SELECT 1 FROM DUAL")
        cursor.close()
        conn.close()
        latency = int((time.time() - start) * 1000)
        logger.info(f"Oracle 连接测试成功，延迟={latency}ms")
        return {"status": "up", "latency_ms": latency}
    except Exception as e:
        logger.error(f"Oracle 连接测试失败: {e}")
        return {"status": "down", "message": str(e)}


def fetch_department_list(config: dict) -> List[str]:
    """从 Oracle 动态获取科室列表"""
    conn = get_oracle_connection(config)
    try:
        cursor = conn.cursor()
        sql = "SELECT DISTINCT 所在科室名称 FROM jhemr.v_zybr WHERE 所在科室名称 IS NOT NULL ORDER BY 所在科室名称"
        logger.info(f"查询科室列表 SQL: {sql}")
        cursor.execute(sql)
        depts = [row[0] for row in cursor.fetchall()]
        cursor.close()
        logger.info(f"查询到科室列表: {depts}")
        return depts
    finally:
        conn.close()


def fetch_records(config: dict, dept_list: List[str], query_date: str) -> List[dict]:
    """
    从 Oracle 查询病程记录与护理记录（生产环境字段）
    """
    conn = get_oracle_connection(config)
    try:
        if dept_list:
            placeholders = ",".join([f":d{i}" for i in range(len(dept_list))])
            dept_filter = f"a.所在科室名称 IN ({placeholders})"
            params = {f"d{i}": d for i, d in enumerate(dept_list)}
        else:
            dept_filter = "1=1"
            params = {}

        params["query_date"] = query_date

        sql = f"""
            SELECT
                a.患者ID, a.次数, a.住院号, a.患者姓名, a.性别, a.出生日期, a.入院日期,
                a.BED_NO AS 床号, a.入院诊断, a.入院病情,
                a.护理级别 AS 医嘱护理级别, a.所在科室名称, a.管床医生,
                b.病历标题时间, b.病历名称, b.创建人 AS 病历创建人, b.病历内容,
                c.护理记录时间, c.护理单类型, c.记录人 AS 护理记录人,
                c.体温, c.心率脉搏, c.呼吸, c.血压, c.血氧饱和度, c.血糖, c.意识神志,
                c.氧疗_鼻导管, c.氧疗_面罩,
                c.入量_名称, c.入量_途径, c.入量_量, c.出量_名称, c.出量_量, c.尿量,
                c.皮肤情况, c.刀口情况, c.管道护理, c.高危风险,
                c.病情观察及护理措施, c.护士签名
            FROM jhemr.v_zybr a
            LEFT JOIN jhemr.v_bcjl b ON a.患者ID = b.患者ID AND a.次数 = b.次数
            LEFT JOIN ydhl.v_hljl c ON c.患者ID = b.患者ID || '_' || b.次数
                AND TO_CHAR(b.病历标题时间, 'yyyy-mm-dd') = TO_CHAR(c.护理记录时间, 'yyyy-mm-dd')
            WHERE {dept_filter}
              AND TO_CHAR(b.病历标题时间, 'yyyy-mm-dd') = :query_date
            ORDER BY a.患者ID, a.次数, b.病历标题时间, c.护理记录时间
        """

        logger.info(f"查询病历记录 SQL params: query_date={query_date}, dept_list={dept_list}")
        cursor = conn.cursor()
        cursor.execute(sql, params)
        columns = [desc[0] for desc in cursor.description]
        rows = cursor.fetchall()
        cursor.close()

        records = [dict(zip(columns, row)) for row in rows]
        logger.info(f"查询到 {len(records)} 条记录 (日期={query_date}, 科室={dept_list})")
        return records
    finally:
        conn.close()


def group_by_patient(records: List[dict]) -> dict:
    """按患者ID+次数分组，避免同一患者不同住院次数的记录混在一起"""
    grouped = {}
    for r in records:
        pid = r.get("患者ID", "unknown")
        visit = r.get("次数", "")
        key = f"{pid}_{visit}" if visit else pid
        if key not in grouped:
            grouped[key] = []
        grouped[key].append(r)
    return grouped


def build_mr_text(record: dict) -> str:
    """将单条记录组装为结构化文本"""
    return f"""
【患者信息】
姓名：{record.get('患者姓名', '未知')} | 性别：{record.get('性别', '')} | 出生日期：{record.get('出生日期', '')}
住院号：{record.get('住院号', '')} | 次数：{record.get('次数', '')}
科室：{record.get('所在科室名称', '')} | 床号：{record.get('床号', '')} | 管床医生：{record.get('管床医生', '')}
入院日期：{record.get('入院日期', '')} | 入院诊断：{record.get('入院诊断', '')} | 入院病情：{record.get('入院病情', '')}
医嘱护理级别：{record.get('医嘱护理级别', '')}

【病程记录】（时间：{record.get('病历标题时间', '')} | 名称：{record.get('病历名称', '')} | 创建人：{record.get('病历创建人', '')}）
{record.get('病历内容', '（无）')}

【护理记录】（时间：{record.get('护理记录时间', '')} | 类型：{record.get('护理单类型', '')} | 记录人：{record.get('护理记录人', '')}）
生命体征：体温{record.get('体温', '')} 心率{record.get('心率脉搏', '')} 呼吸{record.get('呼吸', '')} 血压{record.get('血压', '')} 血氧{record.get('血氧饱和度', '')} 血糖{record.get('血糖', '')} 意识{record.get('意识神志', '')}
氧疗：鼻导管{record.get('氧疗_鼻导管', '')} 面罩{record.get('氧疗_面罩', '')}
出入量：入量(名称{record.get('入量_名称', '')} 途径{record.get('入量_途径', '')} 量{record.get('入量_量', '')}) 出量(名称{record.get('出量_名称', '')} 量{record.get('出量_量', '')}) 尿量{record.get('尿量', '')}
专科评估：皮肤{record.get('皮肤情况', '')} | 刀口{record.get('刀口情况', '')} | 管道{record.get('管道护理', '')} | 高危风险{record.get('高危风险', '')}
护理观察：{record.get('病情观察及护理措施', '（无）')}
护士签名：{record.get('护士签名', '')}
""".strip()


def build_mr_text_combined(patient_records: List[dict]) -> str:
    """将同一患者的多条记录合并为一段结构化文本（包含所有生产字段）"""
    if not patient_records:
        return ""

    first = patient_records[0]
    header = f"""
【患者信息】
姓名：{first.get('患者姓名', '未知')} | 性别：{first.get('性别', '')} | 出生日期：{first.get('出生日期', '')} | 住院号：{first.get('住院号', '')} | 次数：{first.get('次数', '')}
科室：{first.get('所在科室名称', '')} | 床号：{first.get('床号', '')} | 管床医生：{first.get('管床医生', '')}
入院日期：{first.get('入院日期', '')} | 入院诊断：{first.get('入院诊断', '')} | 入院病情：{first.get('入院病情', '')} | 医嘱护理级别：{first.get('医嘱护理级别', '')}
""".strip()

    sections = []
    for i, r in enumerate(patient_records, 1):
        section = f"""
--- 第 {i} 条记录 ---
【病程记录】（时间：{r.get('病历标题时间', '')} | 名称：{r.get('病历名称', '')} | 创建人：{r.get('病历创建人', '')}）
{r.get('病历内容', '（无）')}

【护理记录】（时间：{r.get('护理记录时间', '')} | 类型：{r.get('护理单类型', '')} | 记录人：{r.get('护理记录人', '')}）
生命体征：体温{r.get('体温', '')} 心率{r.get('心率脉搏', '')} 呼吸{r.get('呼吸', '')} 血压{r.get('血压', '')} 血氧{r.get('血氧饱和度', '')} 血糖{r.get('血糖', '')} 意识{r.get('意识神志', '')}
氧疗：鼻导管{r.get('氧疗_鼻导管', '')} 面罩{r.get('氧疗_面罩', '')}
出入量：入量(名称{r.get('入量_名称', '')} 途径{r.get('入量_途径', '')} 量{r.get('入量_量', '')}) 出量(名称{r.get('出量_名称', '')} 量{r.get('出量_量', '')}) 尿量{r.get('尿量', '')}
专科评估：皮肤{r.get('皮肤情况', '')} | 刀口{r.get('刀口情况', '')} | 管道{r.get('管道护理', '')} | 高危风险{r.get('高危风险', '')}
护理观察：{r.get('病情观察及护理措施', '（无）')}
护士签名：{r.get('护士签名', '')}
""".strip()
        sections.append(section)

    return header + "\n\n" + "\n\n".join(sections)
