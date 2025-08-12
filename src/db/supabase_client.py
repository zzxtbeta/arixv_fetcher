"""Generic Supabase client wrapper (optional).

Provides minimal, table-agnostic helpers for basic CRUD operations. If
`SUPABASE_URL` or `SUPABASE_ANON_KEY` are not set, the client is disabled
and methods will raise a clear RuntimeError when used.
"""

import os
import logging
from typing import List, Dict, Any, Optional, Tuple, Union

try:
    from supabase import create_client, Client
except Exception:  # pragma: no cover
    create_client = None  # type: ignore
    Client = object  # type: ignore

logger = logging.getLogger(__name__)


class SupabaseClient:
    """Generic Supabase client wrapper."""

    def __init__(self) -> None:
        url = os.getenv("SUPABASE_URL")
        key = os.getenv("SUPABASE_ANON_KEY")
        if not url or not key or create_client is None:
            self.client: Optional[Client] = None
            if create_client is None:
                logger.warning("supabase-py not installed; Supabase client disabled")
            else:
                logger.info("SUPABASE_URL or SUPABASE_ANON_KEY not set; Supabase client disabled")
        else:
            try:
                self.client = create_client(url, key)
                logger.info("Supabase client initialized")
            except Exception as e:
                self.client = None
                logger.error(f"Failed to initialize Supabase client: {e}")

    def _ensure(self) -> Client:
        if self.client is None:
            raise RuntimeError("Supabase client is not configured. Set SUPABASE_URL and SUPABASE_ANON_KEY.")
        return self.client

    # --- Query helpers ---

    def select(
        self,
        table: str,
        columns: str = "*",
        filters: Optional[Dict[str, Any]] = None,
        order_by: Optional[Tuple[str, bool]] = None,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        try:
            client = self._ensure()
            q = client.table(table).select(columns)
            if filters:
                for k, v in filters.items():
                    if isinstance(v, (list, tuple)):
                        q = q.in_(k, list(v))
                    elif v is None:
                        q = q.is_(k, None)
                    else:
                        q = q.eq(k, v)
            if order_by:
                col, asc = order_by
                q = q.order(col, desc=not asc)
            if limit is not None:
                q = q.limit(limit)
            if offset is not None:
                q = q.range(offset, (offset + (limit or 0) - 1) if limit else offset)
            resp = q.execute()
            return resp.data or []
        except Exception as e:
            logger.error(f"Supabase select failed: {e}")
            return []
    
    def select_in(
        self,
        table: str,
        column: str,
        values: List[Any],
        columns: str = "*",
        order_by: Optional[Tuple[str, bool]] = None,
        limit: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        try:
            client = self._ensure()
            q = client.table(table).select(columns).in_(column, values)
            if order_by:
                col, asc = order_by
                q = q.order(col, desc=not asc)
            if limit is not None:
                q = q.limit(limit)
            resp = q.execute()
            return resp.data or []
        except Exception as e:
            logger.error(f"Supabase select_in failed: {e}")
            return []

    def select_ilike(
        self,
        table: str,
        column: str,
        pattern: str,
        columns: str = "*",
        order_by: Optional[Tuple[str, bool]] = None,
        limit: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """Case-insensitive pattern match using ilike."""
        try:
            client = self._ensure()
            q = client.table(table).select(columns).ilike(column, pattern)
            if order_by:
                col, asc = order_by
                q = q.order(col, desc=not asc)
            if limit is not None:
                q = q.limit(limit)
            resp = q.execute()
            return resp.data or []
        except Exception as e:
            logger.error(f"Supabase select_ilike failed: {e}")
            return []
    
    def count(self, table: str, filters: Optional[Dict[str, Any]] = None) -> int:
        """Return exact row count for a table with optional equality/in filters."""
        try:
            client = self._ensure()
            q = client.table(table).select("id", count="exact")
            if filters:
                for k, v in filters.items():
                    if isinstance(v, (list, tuple)):
                        q = q.in_(k, list(v))
                    elif v is None:
                        q = q.is_(k, None)
                    else:
                        q = q.eq(k, v)
            # limit small to reduce payload
            q = q.limit(1)
            resp = q.execute()
            return int(getattr(resp, "count", 0) or 0)
        except Exception as e:
            logger.error(f"Supabase count failed: {e}")
            return 0

    def insert(self, table: str, rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        if not rows:
            return []
        try:
            client = self._ensure()
            resp = client.table(table).insert(rows).execute()
            return resp.data or []
        except Exception as e:
            logger.error(f"Supabase insert failed: {e}")
            return []
    
    def upsert(
        self,
        table: str,
        rows: List[Dict[str, Any]],
        on_conflict: Optional[Union[str, List[str]]] = None,
    ) -> List[Dict[str, Any]]:
        if not rows:
            return []
        try:
            client = self._ensure()
            q = client.table(table).upsert(rows)
            if on_conflict:
                if isinstance(on_conflict, list):
                    q = q.on_conflict(",".join(on_conflict))
                else:
                    q = q.on_conflict(on_conflict)
            resp = q.execute()
            return resp.data or []
        except Exception as e:
            logger.error(f"Supabase upsert failed: {e}")
            return []
    
    def update(self, table: str, values: Dict[str, Any], filters: Dict[str, Any]) -> int:
        try:
            client = self._ensure()
            q = client.table(table).update(values)
            for k, v in filters.items():
                if isinstance(v, (list, tuple)):
                    q = q.in_(k, list(v))
                elif v is None:
                    q = q.is_(k, None)
                else:
                    q = q.eq(k, v)
            resp = q.execute()
            data = resp.data or []
            return len(data)
        except Exception as e:
            logger.error(f"Supabase update failed: {e}")
            return 0

    def delete(self, table: str, filters: Dict[str, Any]) -> int:
        try:
            client = self._ensure()
            q = client.table(table).delete()
            for k, v in filters.items():
                if isinstance(v, (list, tuple)):
                    q = q.in_(k, list(v))
                elif v is None:
                    q = q.is_(k, None)
                else:
                    q = q.eq(k, v)
            resp = q.execute()
            data = resp.data or []
            return len(data)
        except Exception as e:
            logger.error(f"Supabase delete failed: {e}")
            return 0


# Create singleton instance
supabase_client = SupabaseClient()