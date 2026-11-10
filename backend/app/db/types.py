"""跨数据库兼容的类型：开发用 SQLite，生产用 PostgreSQL。"""

from __future__ import annotations

from typing import Any

from sqlalchemy import JSON, BigInteger, Integer, TypeDecorator
from sqlalchemy.dialects.postgresql import ARRAY, JSONB

# BIGSERIAL（PG）/ INTEGER（SQLite）
BigIntPK = BigInteger().with_variant(Integer, "sqlite")

# JSONB（PG）/ JSON（SQLite）
JSONDoc = JSON().with_variant(JSONB, "postgresql")


class BigIntArray(TypeDecorator[list[int]]):
    """BIGINT[]（PG，可走 GIN 索引）/ JSON 数组（SQLite）。"""

    impl = JSON
    cache_ok = True

    def load_dialect_impl(self, dialect: Any) -> Any:
        if dialect.name == "postgresql":
            return dialect.type_descriptor(ARRAY(BigInteger))
        return dialect.type_descriptor(JSON())
