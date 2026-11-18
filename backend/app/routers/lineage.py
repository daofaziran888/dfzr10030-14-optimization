"""数据血缘追踪 DAG 拓扑接口：返回节点、连线图结构。"""
from __future__ import annotations

import csv
import io
import json
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import StreamingResponse

from app.schemas import ActionPayload, ActionResult, EntryPayload, PageResult
from app.services.dedup_impact import SCOPE_WINDOW, service as impact_service
from app.services.lineage import LineageService

router = APIRouter(prefix="/api/lineage", tags=["数据血缘追踪"])
service = LineageService()
LIST_FIELDS = ["关系编号", "上游节点", "下游节点", "来源字段", "目标字段", "转换说明", "采集批次", "关系版本"]
STATUSES = ["草稿", "已记录", "已验证", "已归档"]


def csv_cell(value: Any) -> str:
    text = str(value) if value is not None else ""
    if text and text[0] in "=+-@":
        text = "'" + text
    return '"' + text.replace('"', '""') + '"'


@router.get("")
def get_graph() -> dict[str, Any]:
    """返回节点与边组成的 DAG 图数据。"""
    return service.get_graph()


@router.get("/export")
def export_entries() -> StreamingResponse:
    nodes, edges = service.raw_data()
    buf = io.StringIO(newline="")
    writer = csv.writer(buf)
    writer.writerow(["type", "id", "name", "from", "to", "label", "status"])
    for node in nodes:
        writer.writerow(["node", node.get("id",""), csv_cell(node.get("name","")), "", "", "", node.get("status","")])
    for edge in edges:
        writer.writerow(["edge", "", "", edge.get("from",""), edge.get("to",""), edge.get("label",""), ""])
    return StreamingResponse(iter([buf.getvalue()]), media_type="text/csv; charset=utf-8",
                             headers={"Content-Disposition": "attachment; filename=lineage.csv"})


@router.get("/dedup-impact/ledger")
def dedup_impact_ledger() -> dict[str, Any]:
    """血缘服务读取重复影响摘要后落入的待确认台账。"""
    rows = impact_service.ledger()
    summaries = impact_service.list_summaries()
    windows = []
    for summary in (item for item in summaries if item.get("scope") == SCOPE_WINDOW):
        window = summary["window"]
        window_rows = [row for row in rows if row["window"] == window]
        windows.append({
            "window": window,
            "summary_id": summary.get("id"),
            "summary_no": summary.get("summary_no"),
            "strategy_code": summary.get("strategy_code"),
            "version": summary.get("version"),
            "status": summary.get("status"),
            "record_count": len(window_rows),
            "pending_count": sum(1 for row in window_rows if row.get("status") == "待确认"),
            "lineage_record_ids": sorted(
                int(row["lineage_record_id"]) for row in window_rows if row.get("lineage_record_id")
            ),
        })
    return {
        "items": rows,
        "total": len(rows),
        "windows": windows,
        "summary_count": len(summaries),
        "options": [
            {"window": item["window"], "strategy_code": item["strategy_code"], "version": item["version"]}
            for item in impact_service.window_options()
        ],
    }


@router.post("/dedup-impact/{window}/push")
def push_dedup_impact(window: str) -> ActionResult:
    """血缘服务读取重复影响摘要，把被替换记录落入待确认台账。"""
    try:
        summary, message = impact_service.push_to_lineage(window)
    except KeyError:
        return ActionResult(ok=False, message=f"窗口 {window} 没有可读取的重复影响摘要")
    return ActionResult(ok=True, message=message, entry=summary)


@router.post("/dedup-impact/{window}/confirm")
def confirm_dedup_impact(window: str) -> ActionResult:
    """确认待确认台账：确认后血缘服务才能接力生成业务记录。"""
    try:
        summary, message = impact_service.confirm_ledger(window)
    except KeyError:
        return ActionResult(ok=False, message=f"窗口 {window} 没有可读取的重复影响摘要")
    return ActionResult(ok=True, message=message, entry=summary)


@router.post("/dedup-impact/{window}/relay")
def relay_dedup_impact(window: str) -> ActionResult:
    """血缘服务接力摘要，生成可供去重服务回查的业务记录。"""
    try:
        summary, message = impact_service.relay(window)
    except KeyError:
        return ActionResult(ok=False, message=f"窗口 {window} 没有可读取的重复影响摘要")
    return ActionResult(ok=True, message=message, entry=summary)


@router.get("/dedup-impact/{window}/lookup")
def lookup_dedup_impact(window: str) -> dict[str, Any]:
    """去重服务按窗口回查摘要对应的血缘业务记录。"""
    return impact_service.lookup(window)


@router.get("/{entry_id}")
def get_entry(entry_id: int) -> dict:
    entry = service.get_entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"血缘关系 {entry_id} 不存在")
    return entry


@router.post("")
def create_entry(payload: EntryPayload) -> ActionResult:
    entry_or_none, missing = service.create_entry(payload.values)
    if missing:
        return ActionResult(ok=False, message=f"缺少必填字段：{'、'.join(missing)}")
    return ActionResult(ok=True, message="血缘关系已登记", entry=entry_or_none)


@router.post("/{entry_id}/actions")
def run_action(entry_id: int, payload: ActionPayload) -> ActionResult:
    entry_or_none, message = service.run_action(entry_id, payload.action)
    if entry_or_none is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry_or_none)
