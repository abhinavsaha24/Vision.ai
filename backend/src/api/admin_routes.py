"""
Admin API routes — requires admin role.

Endpoints:
  GET  /admin/users          - list all users
  GET  /admin/system-health  - detailed system health
  POST /admin/disable-user   - disable a user account
"""

from __future__ import annotations

import logging
import time
from typing import Optional

import psutil
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from backend.src.auth.auth_service import require_admin
from backend.src.database.db import get_connection, release_connection

logger = logging.getLogger(__name__)

router = APIRouter()


# --------------------------------------------------
# Request Models
# --------------------------------------------------


class DisableUserRequest(BaseModel):
    user_id: int
    reason: Optional[str] = "Admin action"


# --------------------------------------------------
# GET /admin/users
# --------------------------------------------------


@router.get("/users")
async def list_users(admin: dict = Depends(require_admin)):
    """List all registered users (admin only)."""
    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id, email, role, is_active, created_at FROM users ORDER BY id"
        )
        rows = cursor.fetchall()
        release_connection(conn)

        users = []
        for row in rows:
            users.append(
                {
                    "id": row[0],
                    "email": row[1],
                    "role": row[2] if len(row) > 2 else "user",
                    "is_active": bool(row[3]) if len(row) > 3 else True,
                    "created_at": row[4] if len(row) > 4 else None,
                }
            )

        return {"users": users, "total": len(users)}

    except Exception as e:
        logger.error("Admin list users error: %s", e)
        raise HTTPException(500, str(e))


# --------------------------------------------------
# GET /admin/system-health
# --------------------------------------------------


@router.get("/system-health")
async def system_health(admin: dict = Depends(require_admin)):
    """Detailed system health (admin only)."""
    try:
        cpu_percent = psutil.cpu_percent(interval=0.1)
        memory = psutil.virtual_memory()

        return {
            "status": "operational",
            "cpu_percent": cpu_percent,
            "memory": {
                "total_mb": round(memory.total / 1024 / 1024, 1),
                "used_mb": round(memory.used / 1024 / 1024, 1),
                "percent": memory.percent,
            },
            "uptime_seconds": round(time.time() - psutil.boot_time(), 0),
            "admin": admin.get("user_id"),
        }

    except Exception as e:
        logger.error("System health error: %s", e)
        return {"status": "degraded", "error": str(e)}


# --------------------------------------------------
# POST /admin/disable-user
# --------------------------------------------------


@router.post("/disable-user")
async def disable_user(
    req: DisableUserRequest,
    admin: dict = Depends(require_admin),
):
    """Disable a user account (admin only)."""
    try:
        conn = get_connection()
        cursor = conn.cursor()

        cursor.execute("SELECT id, email FROM users WHERE id=%s", (req.user_id,))
        user = cursor.fetchone()

        if not user:
            release_connection(conn)
            raise HTTPException(404, "User not found")

        cursor.execute("UPDATE users SET is_active=0 WHERE id=%s", (req.user_id,))
        conn.commit()
        release_connection(conn)

        logger.info("Admin {admin.get('user_id')} disabled user {req.user_id}: %s", req.reason)

        return {
            "status": "disabled",
            "user_id": req.user_id,
            "reason": req.reason,
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error("Disable user error: %s", e)
        raise HTTPException(500, str(e))
