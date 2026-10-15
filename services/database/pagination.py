import base64
import json
from datetime import datetime
from typing import Tuple, List, Dict, Any, Optional
from sqlalchemy import select, desc, asc

def encode_cursor(created_at: datetime, item_id: str) -> str:
    """Encodes (created_at, item_id) into base64 cursor."""
    payload = {
        "t": created_at.isoformat() if created_at else None,
        "id": item_id
    }
    raw = json.dumps(payload).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("utf-8")

def decode_cursor(cursor_str: str) -> Tuple[Optional[datetime], Optional[str]]:
    """Decodes base64 cursor into (created_at, item_id)."""
    try:
        raw = base64.urlsafe_b64decode(cursor_str.encode("utf-8")).decode("utf-8")
        data = json.loads(raw)
        t_str = data.get("t")
        dt = datetime.fromisoformat(t_str) if t_str else None
        return dt, data.get("id")
    except Exception:
        return None, None

def build_cursor_page_response(
    items: List[Any],
    limit: int,
    get_created_at_and_id_fn=lambda x: (getattr(x, "created_at", None), getattr(x, "id", None))
) -> Dict[str, Any]:
    """Builds standard cursor pagination envelope with next_cursor and has_more flag."""
    has_more = len(items) > limit
    page_items = items[:limit]

    next_cursor = None
    if has_more and page_items:
        last_item = page_items[-1]
        c_at, i_id = get_created_at_and_id_fn(last_item)
        if c_at and i_id:
            next_cursor = encode_cursor(c_at, i_id)

    return {
        "items": page_items,
        "next_cursor": next_cursor,
        "has_more": has_more,
        "count": len(page_items)
    }


async def paginate_query(
    db,
    stmt,
    model,
    limit: int = 50,
    cursor: Optional[str] = None,
    response: Optional[Any] = None,
    order_by_desc: bool = True
) -> List[Any]:
    """Executes cursor-paginated query and sets X-Next-Cursor / X-Has-More response headers."""
    if cursor and hasattr(model, "created_at"):
        dt, item_id = decode_cursor(cursor)
        if dt:
            if order_by_desc:
                stmt = stmt.where(model.created_at < dt)
            else:
                stmt = stmt.where(model.created_at > dt)
    if hasattr(model, "created_at"):
        if order_by_desc:
            stmt = stmt.order_by(desc(model.created_at))
        else:
            stmt = stmt.order_by(asc(model.created_at))
    stmt = stmt.limit(limit + 1)
    res = await db.execute(stmt)
    items = res.scalars().all()
    page = build_cursor_page_response(items, limit)
    if response and page.get("next_cursor"):
        response.headers["X-Next-Cursor"] = page["next_cursor"]
        response.headers["X-Has-More"] = str(page["has_more"]).lower()
    return page["items"]
