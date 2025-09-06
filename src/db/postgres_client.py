"""PostgreSQL client wrapper to replace Supabase SDK operations.

Provides the same interface as SupabaseClient but uses native PostgreSQL operations
through psycopg3 for better compatibility with local PostgreSQL instances.
"""

import os
import logging
from typing import List, Dict, Any, Optional, Tuple, Union
from src.db.database import DatabaseManager

logger = logging.getLogger(__name__)


class PostgreSQLClient:
    """PostgreSQL client wrapper with the same interface as SupabaseClient."""

    def __init__(self) -> None:
        """Initialize PostgreSQL client."""
        self.db_uri = os.getenv("DATABASE_URL")
        if not self.db_uri:
            logger.warning("DATABASE_URL not set; PostgreSQL client disabled")
        else:
            logger.info("PostgreSQL client initialized")

    async def _ensure_pool(self):
        """Ensure database pool is initialized."""
        if not self.db_uri:
            raise RuntimeError("PostgreSQL client is not configured. Set DATABASE_URL.")
        
        # Initialize database manager if not already done
        await DatabaseManager.initialize(self.db_uri)
        return await DatabaseManager.get_pool()

    # --- Query helpers ---

    async def select(
        self,
        table: str,
        columns: str = "*",
        filters: Optional[Dict[str, Any]] = None,
        order_by: Optional[Tuple[str, bool]] = None,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """Select records with optional filtering, ordering, and pagination."""
        try:
            pool = await self._ensure_pool()
            
            sql = f"SELECT {columns} FROM {table}"
            params = []
            
            # Add WHERE clause
            if filters:
                conditions = []
                for key, value in filters.items():
                    if key.endswith("__isnull"):
                        field = key[:-8]
                        if value:
                            conditions.append(f"{field} IS NULL")
                        else:
                            conditions.append(f"{field} IS NOT NULL")
                    elif key.endswith("__gte"):
                        field = key[:-5]
                        conditions.append(f"{field} >= %s")
                        params.append(value)
                    elif key.endswith("__lte"):
                        field = key[:-5]
                        conditions.append(f"{field} <= %s")
                        params.append(value)
                    elif key.endswith("__in"):
                        field = key[:-4]
                        if value:
                            placeholders = ",".join(["%s"] * len(value))
                            conditions.append(f"{field} IN ({placeholders})")
                            params.extend(value)
                    else:
                        conditions.append(f"{key} = %s")
                        params.append(value)
                
                if conditions:
                    sql += " WHERE " + " AND ".join(conditions)
            
            # Add ORDER BY clause
            if order_by:
                col, asc = order_by
                direction = "ASC" if asc else "DESC"
                sql += f" ORDER BY {col} {direction}"
            
            # Add LIMIT and OFFSET
            if limit is not None:
                sql += f" LIMIT %s"
                params.append(limit)
            
            if offset is not None:
                sql += f" OFFSET %s"
                params.append(offset)
            
            async with pool.connection() as conn:
                async with DatabaseManager.get_dict_cursor(conn) as cur:
                    await cur.execute(sql, params)
                    rows = await cur.fetchall()
                    return [dict(row) for row in rows]
                    
        except Exception as e:
            logger.error(f"PostgreSQL select failed: {e}")
            return []
    
    async def select_in(
        self,
        table: str,
        column: str,
        values: List[Any],
        columns: str = "*",
        order_by: Optional[Tuple[str, bool]] = None,
        limit: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """Select records where column value is in the provided list."""
        try:
            if not values:
                return []
                
            pool = await self._ensure_pool()
            
            # Build SQL query with IN clause
            placeholders = ','.join(['%s'] * len(values))
            sql = f"SELECT {columns} FROM {table} WHERE {column} IN ({placeholders})"
            params = list(values)
            
            # Add ORDER BY clause
            if order_by:
                col, asc = order_by
                direction = "ASC" if asc else "DESC"
                sql += f" ORDER BY {col} {direction}"
            
            # Add LIMIT
            if limit is not None:
                sql += f" LIMIT %s"
                params.append(limit)
            
            async with pool.connection() as conn:
                async with DatabaseManager.get_dict_cursor(conn) as cur:
                    await cur.execute(sql, params)
                    rows = await cur.fetchall()
                    return [dict(row) for row in rows]
                    
        except Exception as e:
            logger.error(f"PostgreSQL select_in failed: {e}")
            return []

    async def select_ilike(
        self,
        table: str,
        column: str,
        pattern: str,
        columns: str = "*",
        order_by: Optional[Tuple[str, bool]] = None,
        limit: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """Case-insensitive pattern match using ILIKE."""
        try:
            pool = await self._ensure_pool()
            
            # Ensure pattern is a string, not a Query object
            pattern_str = str(pattern) if pattern is not None else ""
            
            sql = f"SELECT {columns} FROM {table} WHERE {column} ILIKE %s"
            params = [pattern_str]
            
            # Add ORDER BY clause
            if order_by:
                col, asc = order_by
                direction = "ASC" if asc else "DESC"
                sql += f" ORDER BY {col} {direction}"
            
            # Add LIMIT
            if limit is not None:
                sql += f" LIMIT %s"
                params.append(limit)
            
            async with pool.connection() as conn:
                async with DatabaseManager.get_dict_cursor(conn) as cur:
                    await cur.execute(sql, params)
                    rows = await cur.fetchall()
                    return [dict(row) for row in rows]
                    
        except Exception as e:
            logger.error(f"PostgreSQL select_ilike failed: {e}")
            return []
    
    async def count(self, table: str, filters: Optional[Dict[str, Any]] = None) -> int:
        """Return row count for a table with optional filters."""
        try:
            pool = await self._ensure_pool()
            
            sql = f"SELECT COUNT(*) as count FROM {table}"
            params = []
            
            # Add WHERE clause
            if filters:
                conditions = []
                for k, v in filters.items():
                    if isinstance(v, (list, tuple)):
                        placeholders = ','.join(['%s'] * len(v))
                        conditions.append(f"{k} = ANY(ARRAY[{placeholders}])")
                        params.extend(v)
                    elif v is None:
                        conditions.append(f"{k} IS NULL")
                    else:
                        conditions.append(f"{k} = %s")
                        params.append(v)
                
                if conditions:
                    sql += " WHERE " + " AND ".join(conditions)
            
            async with pool.connection() as conn:
                async with DatabaseManager.get_dict_cursor(conn) as cur:
                    await cur.execute(sql, params)
                    result = await cur.fetchone()
                    return result['count'] if result else 0
                    
        except Exception as e:
            logger.error(f"PostgreSQL count failed: {e}")
            return 0
    
    async def count_exact(self, table: str, filters: Optional[Dict[str, Any]] = None) -> int:
        """Return exact row count for a table with optional filters.
        
        Note: This is the same as count() since PostgreSQL COUNT(*) is always exact.
        """
        return await self.count(table, filters)

    async def insert(self, table: str, rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Insert rows into a table and return the inserted rows."""
        if not rows:
            return []
            
        try:
            pool = await self._ensure_pool()
            
            # Get column names from first row
            columns = list(rows[0].keys())
            column_names = ', '.join(columns)
            
            # Build placeholders for values
            value_placeholders = ', '.join(['%s'] * len(columns))
            values_clause = ', '.join([f"({value_placeholders})" for _ in rows])
            
            # Flatten all values
            params = []
            for row in rows:
                for col in columns:
                    params.append(row.get(col))
            
            sql = f"INSERT INTO {table} ({column_names}) VALUES {values_clause} RETURNING *"
            
            async with pool.connection() as conn:
                async with DatabaseManager.get_dict_cursor(conn) as cur:
                    await cur.execute(sql, params)
                    result_rows = await cur.fetchall()
                    return [dict(row) for row in result_rows]
                    
        except Exception as e:
            logger.error(f"PostgreSQL insert failed: {e}")
            return []
    
    async def upsert(
        self,
        table: str,
        rows: List[Dict[str, Any]],
        on_conflict: Optional[Union[str, List[str]]] = None,
    ) -> List[Dict[str, Any]]:
        """Insert or update rows using ON CONFLICT clause."""
        if not rows:
            return []
            
        try:
            pool = await self._ensure_pool()
            
            # Get column names from first row
            columns = list(rows[0].keys())
            column_names = ', '.join(columns)
            
            # Build placeholders for values
            value_placeholders = ', '.join(['%s'] * len(columns))
            values_clause = ', '.join([f"({value_placeholders})" for _ in rows])
            
            # Flatten all values
            params = []
            for row in rows:
                for col in columns:
                    params.append(row.get(col))
            
            sql = f"INSERT INTO {table} ({column_names}) VALUES {values_clause}"
            
            # Add ON CONFLICT clause
            if on_conflict:
                if isinstance(on_conflict, list):
                    conflict_columns = ', '.join(on_conflict)
                else:
                    conflict_columns = on_conflict
                
                # Build UPDATE clause for all columns except conflict columns
                conflict_set = set(on_conflict if isinstance(on_conflict, list) else [on_conflict])
                update_columns = [col for col in columns if col not in conflict_set]
                update_clause = ', '.join([f"{col} = EXCLUDED.{col}" for col in update_columns])
                
                sql += f" ON CONFLICT ({conflict_columns}) DO UPDATE SET {update_clause}"
            else:
                sql += " ON CONFLICT DO NOTHING"
            
            sql += " RETURNING *"
            
            async with pool.connection() as conn:
                async with DatabaseManager.get_dict_cursor(conn) as cur:
                    await cur.execute(sql, params)
                    result_rows = await cur.fetchall()
                    return [dict(row) for row in result_rows]
                    
        except Exception as e:
            logger.error(f"PostgreSQL upsert failed: {e}")
            return []
    
    async def update(self, table: str, values: Dict[str, Any], filters: Dict[str, Any]) -> int:
        """Update rows in a table and return the number of affected rows."""
        try:
            pool = await self._ensure_pool()
            
            # Build SET clause
            set_clauses = []
            params = []
            for k, v in values.items():
                set_clauses.append(f"{k} = %s")
                params.append(v)
            
            set_clause = ', '.join(set_clauses)
            
            # Build WHERE clause
            where_conditions = []
            for k, v in filters.items():
                if isinstance(v, (list, tuple)):
                    placeholders = ','.join(['%s'] * len(v))
                    where_conditions.append(f"{k} = ANY(ARRAY[{placeholders}])")
                    params.extend(v)
                elif v is None:
                    where_conditions.append(f"{k} IS NULL")
                else:
                    where_conditions.append(f"{k} = %s")
                    params.append(v)
            
            where_clause = ' AND '.join(where_conditions)
            
            sql = f"UPDATE {table} SET {set_clause} WHERE {where_clause}"
            
            async with pool.connection() as conn:
                async with conn.cursor() as cur:
                    await cur.execute(sql, params)
                    return cur.rowcount
                    
        except Exception as e:
            logger.error(f"PostgreSQL update failed: {e}")
            return 0

    async def delete(self, table: str, filters: Dict[str, Any]) -> int:
        """Delete rows from a table and return the number of affected rows."""
        try:
            pool = await self._ensure_pool()
            
            # Build WHERE clause
            where_conditions = []
            params = []
            for k, v in filters.items():
                if isinstance(v, (list, tuple)):
                    placeholders = ','.join(['%s'] * len(v))
                    where_conditions.append(f"{k} = ANY(ARRAY[{placeholders}])")
                    params.extend(v)
                elif v is None:
                    where_conditions.append(f"{k} IS NULL")
                else:
                    where_conditions.append(f"{k} = %s")
                    params.append(v)
            
            where_clause = ' AND '.join(where_conditions)
            
            sql = f"DELETE FROM {table} WHERE {where_clause}"
            
            async with pool.connection() as conn:
                async with conn.cursor() as cur:
                    await cur.execute(sql, params)
                    return cur.rowcount
                    
        except Exception as e:
            logger.error(f"PostgreSQL delete failed: {e}")
            return 0

    # Synchronous wrapper methods to maintain compatibility with existing code
    def select_sync(self, *args, **kwargs):
        """Synchronous wrapper for select method."""
        import asyncio
        return asyncio.run(self.select(*args, **kwargs))
    
    def select_in_sync(self, *args, **kwargs):
        """Synchronous wrapper for select_in method."""
        import asyncio
        return asyncio.run(self.select_in(*args, **kwargs))
    
    def select_ilike_sync(self, *args, **kwargs):
        """Synchronous wrapper for select_ilike method."""
        import asyncio
        return asyncio.run(self.select_ilike(*args, **kwargs))
    
    def count_sync(self, *args, **kwargs):
        """Synchronous wrapper for count method."""
        import asyncio
        return asyncio.run(self.count(*args, **kwargs))
    
    def count_exact_sync(self, *args, **kwargs):
        """Synchronous wrapper for count_exact method."""
        import asyncio
        return asyncio.run(self.count_exact(*args, **kwargs))
    
    def insert_sync(self, *args, **kwargs):
        """Synchronous wrapper for insert method."""
        import asyncio
        return asyncio.run(self.insert(*args, **kwargs))
    
    def upsert_sync(self, *args, **kwargs):
        """Synchronous wrapper for upsert method."""
        import asyncio
        return asyncio.run(self.upsert(*args, **kwargs))
    
    def update_sync(self, *args, **kwargs):
        """Synchronous wrapper for update method."""
        import asyncio
        return asyncio.run(self.update(*args, **kwargs))
    
    def delete_sync(self, *args, **kwargs):
        """Synchronous wrapper for delete method."""
        import asyncio
        return asyncio.run(self.delete(*args, **kwargs))


# Create singleton instance
postgres_client = PostgreSQLClient()
