"""
Backwards-compatible shim.
Redirects to the new backend.src.api.main module.

This ensures both old and new start commands work:
  - python -m src.api.main         (old Render deploy)
  - python -m backend.src.api.main (new)
"""

from backend.src.api.main import app  # noqa: F401

if __name__ == "__main__":
    import os
    import uvicorn
    port = int(os.environ.get("PORT", 10000))
    uvicorn.run("backend.src.api.main:app", host="0.0.0.0", port=port, reload=False)