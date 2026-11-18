"""采集去重 · 重复影响摘要接口。

列表按窗口聚合，展开后拿到每组重复记录样本；生成摘要、按历史版本核对、以及和
血缘服务的交接（落台账 / 接力业务记录 / 回查）都收在同一组路径下。
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app.schemas import ActionResult, EntryPayload
from app.services.dedup_impact import (
    SCOPE_VERSION,
    SCOPE_WINDOW,
    SCOPES,
    ImpactConflict,
    ImpactLocked,
    service,
)

router = APIRouter(prefix="/api/dedup/impact", tags=["采集去重·重复影响摘要"])


@router.get("")
def list_summaries() -> dict[str, Any]:
    """按窗口列出重复影响摘要；未生成的窗口给出待生成提示。"""
    rows = service.list_summaries()
    windows = service.window_options()
    return {
        "items": rows,
        "total": len(rows),
        "windows": windows,
        "scopes": [
            {"value": SCOPE_WINDOW, "label": "按窗口边界（整段影响）"},
            {"value": SCOPE_VERSION, "label": "按策略版本（新增影响）"},
        ],
    }


@router.get("/preview")
def preview(
    window: str = Query(..., description="策略窗口，例如 2026-09-01"),
    scope: str = Query(default=SCOPE_WINDOW, description="window=整段影响，version=新增影响"),
) -> dict[str, Any]:
    """生成前预览：只按窗口汇总重复记录，不展开全部原始记录，也不落库。"""
    if scope not in SCOPES:
        raise HTTPException(status_code=400, detail=f"口径 {scope} 不在支持范围内")
    try:
        return service.preview(window, scope)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"窗口 {window} 没有可汇总的重复记录样本")


@router.post("")
def generate(payload: EntryPayload) -> ActionResult:
    """生成重复影响摘要；同一窗口同一口径只保留一份，重复生成被拒绝。"""
    window = str(payload.values.get("window") or "").strip()
    scope = str(payload.values.get("scope") or SCOPE_WINDOW).strip()
    if not window:
        return ActionResult(ok=False, message="缺少必填字段：window")
    if scope not in SCOPES:
        return ActionResult(ok=False, message=f"口径 {scope} 不在支持范围内")
    try:
        summary, message = service.generate(window, scope)
    except KeyError:
        return ActionResult(ok=False, message=f"窗口 {window} 没有可汇总的重复记录样本")
    except ImpactConflict as error:
        return ActionResult(ok=False, message=str(error))
    return ActionResult(ok=True, message=message, entry=summary)


@router.get("/{summary_id}")
def get_summary(summary_id: int) -> dict[str, Any]:
    summary = service.get_summary(summary_id)
    if summary is None:
        raise HTTPException(status_code=404, detail=f"重复影响摘要 {summary_id} 不存在")
    return summary


@router.post("/{summary_id}/regenerate")
def regenerate(summary_id: int) -> ActionResult:
    """按历史窗口重算整段影响：数字一致才更新，不一致以历史版本为准并保留原记录。"""
    try:
        summary, message = service.regenerate(summary_id)
    except ImpactLocked as error:
        return ActionResult(ok=False, message=str(error))
    if not summary:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=summary)


@router.post("/{summary_id}/push-lineage")
def push_lineage(summary_id: int) -> ActionResult:
    """把摘要交给血缘服务，落入待确认台账。"""
    summary = service.get_summary(summary_id)
    if summary is None:
        return ActionResult(ok=False, message=f"重复影响摘要 {summary_id} 不存在")
    try:
        updated, message = service.push_to_lineage(summary["window"])
    except KeyError:
        return ActionResult(ok=False, message=f"窗口 {summary['window']} 的摘要未生成")
    return ActionResult(ok=True, message=message, entry=updated)


@router.post("/{summary_id}/relay")
def relay(summary_id: int) -> ActionResult:
    """血缘服务接力摘要，生成可被去重服务回查的业务记录。"""
    summary = service.get_summary(summary_id)
    if summary is None:
        return ActionResult(ok=False, message=f"重复影响摘要 {summary_id} 不存在")
    try:
        updated, message = service.relay(summary["window"])
    except KeyError:
        return ActionResult(ok=False, message=f"窗口 {summary['window']} 的摘要未生成")
    return ActionResult(ok=True, message=message, entry=updated)


@router.get("/{summary_id}/lineage")
def lineage_detail(summary_id: int) -> dict[str, Any]:
    """去重服务回查：这条摘要对应的血缘业务记录。"""
    summary = service.get_summary(summary_id)
    if summary is None:
        raise HTTPException(status_code=404, detail=f"重复影响摘要 {summary_id} 不存在")
    return service.lookup(summary["window"])
