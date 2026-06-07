"""
患者清单路由 —— /api/patients
"""
from fastapi import APIRouter, Depends, Query, HTTPException
from pydantic import BaseModel, Field
from typing import Literal

from app.config import load_config
from app.permissions import require_permission
from app.services.patient_census_service import (
    load_patient_census,
    summarize_patient_census,
    get_qybr_metadata,
    precheck_by_patient_census,
)

router = APIRouter()


class PrecheckRequest(BaseModel):
    mode: Literal["inpatient", "discharged"]
    query_date: str = ""
    dept_filter: list[str] = Field(default_factory=list)
    audit_type_codes: list[str] = Field(default_factory=list)
    limit_patients: int = Field(default=20, ge=1, le=50)


@router.get("/census", summary="患者清单")
def get_patient_census(
    mode: Literal["inpatient", "discharged"] = Query("discharged"),
    query_date: str = Query(""),
    dept_filter: str = Query(""),
    limit: int = Query(50, ge=1, le=500),
    include_sensitive: bool = Query(False, description="当前版本固定脱敏，此参数暂不生效"),
    _user=Depends(require_permission("view_scheduler")),
):
    config = load_config()
    dept_list = [d.strip() for d in dept_filter.split(",") if d.strip()] if dept_filter else []
    # 第一阶段固定脱敏，避免普通只读权限用户通过参数获取明文患者信息。
    masking = True
    try:
        items, _total = load_patient_census(
            config, mode, query_date or None, dept_list, limit, masking_enabled=masking,
        )
    except ValueError as exc:
        raise HTTPException(400, detail=str(exc))
    except RuntimeError as exc:
        raise HTTPException(500, detail=str(exc))

    return {
        "mode": mode,
        "query_date": query_date or "",
        "dept_filter": dept_list,
        "total_returned": len(items),
        "limit": limit,
        "masking_enabled": masking,
        "warnings": ["include_sensitive is disabled in this version"] if include_sensitive else [],
        "items": items,
    }


@router.get("/census/summary", summary="患者统计")
def get_patient_census_summary(
    mode: Literal["inpatient", "discharged"] = Query("discharged"),
    query_date: str = Query(""),
    dept_filter: str = Query(""),
    _user=Depends(require_permission("view_scheduler")),
):
    config = load_config()
    dept_list = [d.strip() for d in dept_filter.split(",") if d.strip()] if dept_filter else []
    try:
        result = summarize_patient_census(config, mode, query_date or None, dept_list)
    except ValueError as exc:
        raise HTTPException(400, detail=str(exc))
    except RuntimeError as exc:
        raise HTTPException(500, detail=str(exc))
    return result


@router.get("/census/metadata", summary="患者视图元数据")
def get_patient_census_metadata(
    _user=Depends(require_permission("view_scheduler")),
):
    config = load_config()
    try:
        return get_qybr_metadata(config)
    except RuntimeError as exc:
        raise HTTPException(500, detail=str(exc))


@router.post("/census/precheck", summary="只读预检")
def do_patient_census_precheck(
    body: PrecheckRequest,
    _user=Depends(require_permission("manage_scheduler")),
):
    config = load_config()
    try:
        result = precheck_by_patient_census(
            config,
            body.mode,
            body.query_date or None,
            body.dept_filter,
            body.audit_type_codes,
            body.limit_patients,
        )
    except ValueError as exc:
        raise HTTPException(400, detail=str(exc))
    except RuntimeError as exc:
        if "already running" in str(exc):
            raise HTTPException(409, detail=str(exc))
        raise HTTPException(500, detail=str(exc))
    return result
