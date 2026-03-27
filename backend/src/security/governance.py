from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import HTTPException

from backend.src.database.db import get_connection, release_connection


ACTION_POLICY: dict[str, set[str]] = {
    "live_trading_enable": {"admin"},
    "emergency_kill_reset": {"admin"},
    "strategy_promotion": {"admin"},
}


def assert_action_allowed(user: dict[str, Any], action: str) -> None:
    role = str(user.get("role", "")).strip().lower()
    allowed = ACTION_POLICY.get(action, {"admin"})
    if role not in allowed:
        raise HTTPException(status_code=403, detail=f"action_forbidden:{action}")


def create_approval_request(
    action: str,
    target: str,
    requested_by: int,
    details: dict[str, Any] | None = None,
    expires_minutes: int = 30,
) -> dict[str, Any]:
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=max(1, int(expires_minutes)))
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO dual_approval_requests(action, target, requested_by, approvals_json, status, expires_at, details_json)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            RETURNING id, created_at
            """,
            (
                action,
                target,
                int(requested_by),
                json.dumps([]),
                "pending",
                expires_at,
                json.dumps(details or {}),
            ),
        )
        row = cur.fetchone()
        conn.commit()
        return {
            "request_id": int(row[0]),
            "action": action,
            "target": target,
            "status": "pending",
            "created_at": row[1].isoformat() if hasattr(row[1], "isoformat") else str(row[1]),
            "expires_at": expires_at.isoformat(),
        }
    finally:
        release_connection(conn)


def approve_request(request_id: int, approver_user_id: int) -> dict[str, Any]:
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT id, action, target, requested_by, approvals_json, status, expires_at
            FROM dual_approval_requests
            WHERE id=%s
            """,
            (int(request_id),),
        )
        row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="approval_request_not_found")

        _id, action, target, requested_by, approvals_json, status, expires_at = row
        if str(status) == "approved":
            return {
                "request_id": int(_id),
                "action": str(action),
                "target": str(target),
                "status": "approved",
                "approvals": json.loads(approvals_json or "[]"),
            }
        if expires_at and datetime.now(timezone.utc) > expires_at:
            raise HTTPException(status_code=410, detail="approval_request_expired")

        approvals = json.loads(approvals_json or "[]")
        approvals = [int(x) for x in approvals if str(x).isdigit()]
        if int(approver_user_id) == int(requested_by):
            raise HTTPException(status_code=400, detail="requester_cannot_self_approve")
        if int(approver_user_id) not in approvals:
            approvals.append(int(approver_user_id))

        next_status = "approved" if len(set(approvals)) >= 2 else "pending"
        cur.execute(
            """
            UPDATE dual_approval_requests
            SET approvals_json=%s, status=%s, updated_at=NOW()
            WHERE id=%s
            """,
            (json.dumps(sorted(set(approvals))), next_status, int(_id)),
        )
        conn.commit()

        return {
            "request_id": int(_id),
            "action": str(action),
            "target": str(target),
            "status": next_status,
            "approvals": sorted(set(approvals)),
        }
    finally:
        release_connection(conn)


def get_request_status(request_id: int) -> dict[str, Any]:
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT id, action, target, requested_by, approvals_json, status, expires_at, created_at
            FROM dual_approval_requests
            WHERE id=%s
            """,
            (int(request_id),),
        )
        row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="approval_request_not_found")

        return {
            "request_id": int(row[0]),
            "action": str(row[1]),
            "target": str(row[2]),
            "requested_by": int(row[3]),
            "approvals": json.loads(row[4] or "[]"),
            "status": str(row[5]),
            "expires_at": row[6].isoformat() if hasattr(row[6], "isoformat") else str(row[6]),
            "created_at": row[7].isoformat() if hasattr(row[7], "isoformat") else str(row[7]),
        }
    finally:
        release_connection(conn)


def is_dual_approval_satisfied(action: str, target: str) -> bool:
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT approvals_json, expires_at
            FROM dual_approval_requests
            WHERE action=%s AND target=%s AND status='approved'
            ORDER BY updated_at DESC
            LIMIT 1
            """,
            (action, target),
        )
        row = cur.fetchone()
        if not row:
            return False
        approvals = json.loads(row[0] or "[]")
        expires_at = row[1]
        if expires_at and datetime.now(timezone.utc) > expires_at:
            return False
        return len(set(int(x) for x in approvals)) >= 2
    finally:
        release_connection(conn)
