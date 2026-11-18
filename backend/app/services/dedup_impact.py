"""采集去重 · 重复影响摘要。

旧口径是把窗口里的原始记录全部展开、逐条比对，运营想知道一次策略调整影响哪些窗口
就得一条条翻记录。这里改成按策略窗口汇总重复记录样本，产出「重复影响摘要」：

- 窗口边界：按窗口整段重算，窗口是影响汇总单位；
- 策略版本边界：只展示当前策略版本新增的影响，版本是影响比较单位。

两个边界结果不同，但摘要里的每个影响数字都能回到唯一一份策略版本。历史版本是核对
口径（以历史版本为准判定），原始记录始终保留，不做删除或覆盖。

摘要同时是血缘服务的输入：血缘服务读取摘要落入待确认台账，确认后接力生成可被去重
服务回查的业务记录。同一窗口同一策略版本只保留一份摘要，重复生成会被拒绝。

样本口径：小组第一条是保留记录，其余是重复后被替换的记录。历史窗口快照里的
duplicate_count 统计窗口内全部重复记录数（含保留记录），replaced_count 统计被替换
记录数，即真正合并掉的记录。
"""
from __future__ import annotations

import copy
import hashlib
import threading
from typing import Any
from datetime import datetime, timezone

from app.store import store

# 示例窗口：version 是当前策略版本，basis_version 是它上一版（新增影响的比较基线）。
# 每个小组里元素的 first_version 表示这条记录从哪个策略版本开始受影响。
WINDOW_FIXTURES: dict[str, dict[str, Any]] = {
    "2026-09-01": {
        "strategy_code": "DEDU-0001",
        "version": "v2",
        "basis_version": "v1",
        "groups": [
            ["v1", "v1", "v1"],
            ["v1", "v1"],
            ["v1", "v1", "v2", "v2"],
            ["v2", "v2"],
            ["v2", "v2", "v2"],
        ],
        "history": {
            "full": {"duplicate_count": 14, "replaced_count": 9},
            "incremental": {"duplicate_count": 7, "replaced_count": 5},
        },
    },
    "2026-09-02": {
        "strategy_code": "DEDU-0002",
        "version": "v3",
        "basis_version": "v2",
        "groups": [
            ["v2", "v2"],
            ["v2", "v2"],
            ["v2", "v3"],
            ["v3", "v3"],
            ["v3"],
        ],
        "history": {
            "full": {"duplicate_count": 10, "replaced_count": 5},
            "incremental": {"duplicate_count": 4, "replaced_count": 2},
        },
    },
    "2026-09-03": {
        "strategy_code": "DEDU-0003",
        "version": "v1",
        "basis_version": None,
        "groups": [
            ["v1", "v1", "v1"],
            ["v1", "v1"],
            ["v1", "v1", "v1", "v1"],
        ],
        "history": {
            "full": {"duplicate_count": 9, "replaced_count": 6},
            "incremental": {"duplicate_count": 9, "replaced_count": 6},
        },
    },
}

SCOPE_WINDOW = "window"
SCOPE_VERSION = "version"
SCOPES = [SCOPE_WINDOW, SCOPE_VERSION]
SCOPE_LABELS = {
    SCOPE_WINDOW: "按窗口边界（整段影响）",
    SCOPE_VERSION: "按策略版本（新增影响）",
}

LEDGER_MODULE = "dedup_impact_ledger"
LINEAGE_MODULE = "lineage"
QUEUE_MODULE = "dedup_impact_queue"

RAW_RECORDS_PER_GROUP = 12
SAMPLE_RECORDS_PER_GROUP = 3


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _digest(*parts: str) -> str:
    return hashlib.sha1("|".join(parts).encode("utf-8")).hexdigest()[:8]


class ImpactConflict(Exception):
    """同一窗口 / 版本已经存在不同口径的摘要，拒绝覆盖。"""


class ImpactLocked(Exception):
    """摘要已被血缘服务接手，不能再重算。"""


class DedupImpactService:
    def __init__(self) -> None:
        self._lock = threading.Lock()

    # ------------------------------------------------------------------ 输入
    def _fixtures(self) -> dict[str, dict[str, Any]]:
        return copy.deepcopy(WINDOW_FIXTURES)

    def list_summaries(self) -> list[dict[str, Any]]:
        """摘要列表：一个窗口一行，带影响数字、策略版本与可展开的记录快照。"""
        rows = store.rows(QUEUE_MODULE)
        order = {window: index for index, window in enumerate(WINDOW_FIXTURES)}
        return sorted(rows, key=lambda row: (order.get(row.get("window"), 99), row.get("scope", "")))

    def get_summary(self, summary_id: int) -> dict[str, Any] | None:
        for row in store.rows(QUEUE_MODULE):
            if int(row.get("id", 0)) == summary_id:
                return row
        return None

    def window_options(self) -> list[dict[str, Any]]:
        """可汇总的窗口清单，供页面下拉选择。"""
        summaries = {
            (row.get("window"), row.get("scope")): row for row in store.rows(QUEUE_MODULE)
        }
        options: list[dict[str, Any]] = []
        for window, fixture in WINDOW_FIXTURES.items():
            summary = summaries.get((window, SCOPE_WINDOW))
            options.append({
                "window": window,
                "strategy_code": fixture["strategy_code"],
                "version": fixture["version"],
                "basis_version": fixture["basis_version"],
                "generated": summary is not None,
                "summary_id": summary.get("id") if summary else None,
            })
        return options

    def find_summary(self, window: str, scope: str = SCOPE_WINDOW) -> dict[str, Any] | None:
        for row in store.rows(QUEUE_MODULE):
            if row.get("window") == window and row.get("scope") == scope:
                return row
        return None

    # ------------------------------------------------------------------ 计算
    def _build(self, window: str, fixture: dict[str, Any], scope: str) -> dict[str, Any]:
        groups = fixture["groups"]
        version = fixture["version"]
        basis = fixture["basis_version"]

        records: list[dict[str, Any]] = []
        replaced_scope_total = 0
        duplicate_scope_total = 0
        for group_index, first_versions in enumerate(groups, start=1):
            group_id = f"{window}-G{group_index:02d}"
            affected = [v for v in first_versions if scope == SCOPE_WINDOW or v == version]
            if not affected:
                continue
            # 窗口口径：组内除保留记录外都算重复；版本口径：只算本版本首次出现的记录。
            in_scope = first_versions if scope == SCOPE_WINDOW else [v for v in first_versions if v == version]
            keep_is_original = first_versions[0] in in_scope
            duplicate_count = len(in_scope)
            replaced_count = duplicate_count - (1 if keep_is_original else 0)
            set_version = version if scope == SCOPE_VERSION else first_versions[0]
            raw_records_avoided = RAW_RECORDS_PER_GROUP - min(len(affected), SAMPLE_RECORDS_PER_GROUP)

            duplicate_scope_total += duplicate_count
            replaced_scope_total += replaced_count

            sample: list[dict[str, Any]] = []
            for seq, first_version in enumerate(in_scope[:SAMPLE_RECORDS_PER_GROUP], start=1):
                is_keep = keep_is_original and seq == 1
                sample.append({
                    "record_id": f"RAW-{window.replace('-', '')}-{group_index:02d}-{seq:02d}",
                    "group": group_id,
                    "first_version": first_version,
                    "role": "保留" if is_keep else "被替换",
                })
            records.append({
                "group": group_id,
                "duplicate_count": duplicate_count,
                "replaced_count": replaced_count,
                "sample_total": len(in_scope),
                "sample_truncated": len(in_scope) > SAMPLE_RECORDS_PER_GROUP,
                "raw_records_avoided": raw_records_avoided,
                "version": set_version,
                "records": sample,
            })

        history = fixture["history"]["full" if scope == SCOPE_WINDOW else "incremental"]
        history_total = int(history["duplicate_count"])
        history_replaced = int(history["replaced_count"])
        return {
            "window": window,
            "scope": scope,
            "scope_label": SCOPE_LABELS[scope],
            "strategy_code": fixture["strategy_code"],
            "version": version,
            "basis_version": basis,
            "version_label": f"{fixture['strategy_code']} {version}",
            "duplicate_count": duplicate_scope_total,
            "replaced_count": replaced_scope_total,
            "window_total_records": sum(len(group) for group in groups),
            "group_count": len(records),
            "replaced_range": (
                f"{records[0]['group']} … {records[-1]['group']}" if records else "—"
            ),
            "replaced_first": records[0]["group"] if records else "—",
            "replaced_last": records[-1]["group"] if records else "—",
            "history_duplicate_count": history_total,
            "history_replaced_count": history_replaced,
            "history_matches": duplicate_scope_total == history_total
            and replaced_scope_total == history_replaced,
            "raw_records_avoided": sum(item["raw_records_avoided"] for item in records),
            "records": records,
        }

    def preview(self, window: str, scope: str = SCOPE_WINDOW) -> dict[str, Any]:
        """生成前预览：只算数字，不落库。"""
        fixture = self._fixtures().get(window)
        if fixture is None:
            raise KeyError(window)
        if scope not in SCOPES:
            raise ValueError(scope)
        summary = self._build(window, fixture, scope)
        existing = self.find_summary(window, scope)
        summary["existing"] = bool(existing)
        summary["existing_id"] = existing.get("id") if existing else None
        return summary

    # ------------------------------------------------------------------ 生成
    def generate(self, window: str, scope: str = SCOPE_WINDOW) -> tuple[dict[str, Any], str]:
        """按窗口 + 口径生成摘要；同窗同口径并发只保留一份，后来者被拒绝。"""
        fixture = self._fixtures().get(window)
        if fixture is None:
            raise KeyError(window)
        if scope not in SCOPES:
            raise ValueError(scope)
        with self._lock:
            existing = self.find_summary(window, scope)
            if existing is not None:
                raise ImpactConflict(
                    f"窗口 {window} 已有{existing.get('scope_label', scope)}摘要 "
                    f"#{existing.get('id')}，同一窗口只保留一份结果"
                )
            summary = self._build(window, fixture, scope)
            rows = store.rows(QUEUE_MODULE)
            summary["id"] = max((int(row.get("id", 0)) for row in rows), default=0) + 1
            summary["summary_no"] = f"IMP-{summary['id']:04d}"
            summary["fingerprint"] = _digest(
                window, scope, summary["strategy_code"], summary["version"],
                str(summary["duplicate_count"]), str(summary["replaced_count"]),
            )
            summary["status"] = "待确认"
            summary["lineage_ledger_id"] = None
            summary["lineage_record_id"] = None
            summary["created_at"] = _now()
            rows.append(summary)
            return summary, "重复影响摘要已生成"

    def regenerate(self, summary_id: int) -> tuple[dict[str, Any], str]:
        """按历史快照重算同一窗口的整段影响；数字对不上时以历史版本为准判定并保留原记录。"""
        summary = self.get_summary(summary_id)
        if summary is None:
            return {}, f"重复影响摘要 {summary_id} 不存在"
        if summary.get("lineage_ledger_id"):
            raise ImpactLocked("摘要已被血缘服务接手，不能再重算")
        fixture = self._fixtures().get(summary["window"])
        if fixture is None:
            return {}, f"窗口 {summary['window']} 已有历史版本，不再重算"
        with self._lock:
            return self._regenerate_locked(summary, fixture)

    def _regenerate_locked(
        self, summary: dict[str, Any], fixture: dict[str, Any]
    ) -> tuple[dict[str, Any], str]:
        fresh = self._build(summary["window"], fixture, summary["scope"])
        fresh["history_matches"] = (
            fresh["duplicate_count"] == summary.get("history_duplicate_count")
            and fresh["replaced_count"] == summary.get("history_replaced_count")
        )
        if not fresh["history_matches"]:
            # 历史版本为准判定：数字不覆盖，原始记录保留。
            summary["verdict"] = "与历史版本不一致"
            summary["verdict_note"] = (
                f"快照 {summary.get('history_duplicate_count')} 条 / 替换 "
                f"{summary.get('history_replaced_count')} 条；本次重算 "
                f"{fresh['duplicate_count']} 条 / 替换 {fresh['replaced_count']} 条。"
                "按历史版本判定，保留原始记录。"
            )
            summary["checked_at"] = _now()
            return summary, "重算结果与历史版本不一致，已按历史版本判定并保留原记录"
        summary["duplicate_count"] = fresh["duplicate_count"]
        summary["replaced_count"] = fresh["replaced_count"]
        summary["records"] = fresh["records"]
        summary["history_matches"] = True
        summary["verdict"] = "与历史版本一致"
        summary["verdict_note"] = ""
        summary["checked_at"] = _now()
        return summary, "重复影响摘要已按历史版本核对一致"

    def ledger(self) -> list[dict[str, Any]]:
        """待确认台账明细：一行一条被替换记录。"""
        return list(store.rows(LEDGER_MODULE))

    def confirm_ledger(self, window: str) -> tuple[dict[str, Any] | None, str]:
        """人工确认台账：确认后血缘服务才能接力生成业务记录。"""
        with self._lock:
            summary = self._owned_summary(window)
            rows = [row for row in store.rows(LEDGER_MODULE) if row.get("window") == window]
            if not rows:
                return summary, f"窗口 {window} 的摘要尚未落入血缘待确认台账"
            pending = [row for row in rows if row.get("status") == "待确认"]
            if not pending:
                return summary, f"窗口 {window} 的待确认台账已全部确认"
            for row in pending:
                row["status"] = "已确认"
                row["confirmed_at"] = _now()
            summary["status"] = "已确认"
            return summary, f"窗口 {window} 的 {len(pending)} 条被替换记录已确认"

    # ------------------------------------------------------------------ 血缘接力
    def _owned_summary(self, window: str) -> dict[str, Any]:
        summary = self.find_summary(window, SCOPE_WINDOW)
        if summary is None:
            raise KeyError(window)
        return summary

    def push_to_lineage(self, window: str) -> tuple[dict[str, Any] | None, str]:
        """把摘要交给血缘服务：读取重复影响摘要并落入待确认台账。"""
        with self._lock:
            summary = self._owned_summary(window)
            if summary.get("lineage_ledger_id"):
                return summary, f"窗口 {window} 的摘要已在血缘待确认台账中（#{summary['lineage_ledger_id']}）"
            ledger_rows = store.rows(LEDGER_MODULE)
            ledger_id = max((int(row.get("id", 0)) for row in ledger_rows), default=0) + 1
            source_version = str(summary.get("version"))
            replaced: list[dict[str, Any]] = []
            for item in summary.get("records", []):
                for record in item.get("records", []):
                    if record.get("role") != "被替换":
                        continue
                    replaced.append({
                        "id": max((int(row.get("id", 0)) for row in ledger_rows), default=0) + 1,
                        "window": window,
                        "summary_id": summary["id"],
                        "summary_no": summary.get("summary_no"),
                        "record_id": record["record_id"],
                        "role": record["role"],
                        "source_version": source_version,
                        "status": "待确认",
                        "lineage_record_id": None,
                        "created_at": _now(),
                    })
            ledger_rows.extend(replaced)
            summary["lineage_ledger_id"] = ledger_id
            summary["lineage_ledger_count"] = len(replaced)
            summary["status"] = "待确认"
            return summary, f"重复影响摘要中的被替换记录已落入血缘待确认台账（{len(replaced)} 条）"

    def relay(self, window: str) -> tuple[dict[str, Any] | None, str]:
        """血缘服务接力摘要，生成可被去重服务回查的业务记录。"""
        with self._lock:
            summary = self._owned_summary(window)
            ledger_rows = [row for row in store.rows(LEDGER_MODULE) if row.get("window") == window]
            if not ledger_rows:
                return summary, f"窗口 {window} 的摘要尚未落入血缘台账，请先读取摘要"
            if summary.get("lineage_record_id"):
                return summary, f"窗口 {window} 的业务记录已生成（#{summary['lineage_record_id']}）"
            created: list[int] = []
            for row in ledger_rows:
                if row.get("status") != "已确认" or row.get("lineage_record_id"):
                    continue
                rows = store.rows(LINEAGE_MODULE)
                record_id = max((int(item.get("id", 0)) for item in rows), default=0) + 1
                upstream = f"dedup:{summary.get('strategy_code')}:{row.get('record_id')}"
                downstream = f"ingest:{window}"
                rows.append({
                    "id": record_id,
                    "status": "已记录",
                    "pending": True,
                    "abnormal": False,
                    "关系编号": f"LINE-DEDUP-{record_id:04d}",
                    "上游节点": upstream,
                    "下游节点": downstream,
                    "来源字段": f"重复影响摘要 {summary.get('summary_no')}",
                    "目标字段": row.get("record_id"),
                    "转换说明": f"按策略版本 {row.get('source_version')} 确认替换",
                    "采集批次": window,
                    "关系版本": row.get("source_version"),
                    "source": "dedup_impact",
                    "dedup_summary_id": summary["id"],
                    "dedup_record_id": row.get("record_id"),
                })
                row["status"] = "已确认"
                row["lineage_record_id"] = record_id
                created.append(record_id)
            if not created:
                return summary, f"窗口 {window} 的业务记录已存在，无需重复生成"
            summary["lineage_record_id"] = created[0]
            summary["lineage_record_ids"] = created
            summary["status"] = "已接力"
            return summary, f"血缘服务已生成 {len(created)} 条业务记录，去重服务可按摘要回查"

    # ------------------------------------------------------------------ 回查
    def lookup(self, window: str) -> dict[str, Any]:
        """去重服务回查：摘要 → 血缘台账 → 业务记录。"""
        summary = self.find_summary(window, SCOPE_WINDOW)
        if summary is None:
            return {"window": window, "found": False, "summary": None, "ledger": [], "lineage_records": []}
        ledger = [row for row in store.rows(LEDGER_MODULE) if row.get("window") == window]
        lineage_ids = {
            int(row["lineage_record_id"])
            for row in ledger
            if row.get("lineage_record_id")
        }
        records = [
            row for row in store.rows(LINEAGE_MODULE)
            if int(row.get("id", 0)) in lineage_ids
        ]
        return {
            "window": window,
            "found": True,
            "summary": summary,
            "ledger": ledger,
            "lineage_records": records,
        }


service = DedupImpactService()
