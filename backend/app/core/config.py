"""全局配置（pydantic-settings 读取 .env）。

约定：所有可调参数集中在此，业务代码禁止直接读 os.environ。
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[2]
PROJECT_DIR = BACKEND_DIR.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(PROJECT_DIR / ".env", BACKEND_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # ---------- 基础 ----------
    APP_NAME: str = "智评导学"
    APP_ENV: str = "dev"
    DEBUG: bool = True
    SECRET_KEY: str = "dev-only-secret-key-please-change-0123456789"
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 120
    API_PREFIX: str = "/api/v1"
    CORS_ORIGINS: str = "http://localhost:5173,http://localhost:4173,http://localhost"
    AUTO_CREATE_TABLES: bool = True

    # ---------- 数据库 ----------
    # 默认 SQLite 便于「克隆即跑」；docker/prod 通过环境变量覆盖为 PostgreSQL
    DATABASE_URL: str = "sqlite+aiosqlite:///./data/app.db"
    DATABASE_URL_SYNC: str = "sqlite:///./data/app.db"
    DB_POOL_SIZE: int = 20
    DB_MAX_OVERFLOW: int = 10
    DB_ECHO: bool = False

    # ---------- Redis / 队列 ----------
    REDIS_URL: str = "redis://localhost:6379/0"
    USE_CELERY: bool = False  # false → 进程内线程池执行异步任务（离线可跑）
    JOB_WORKERS: int = 4
    CACHE_TTL_SEARCH: int = 3600
    JOB_POLL_INTERVAL_MS: int = 1500

    # ---------- 向量库 ----------
    VECTOR_BACKEND: str = "local"  # local | chroma | qdrant
    CHROMA_DIR: str = "./data/chroma"
    QDRANT_URL: str = "http://localhost:6333"
    VECTOR_COLLECTION: str = "course_chunks"
    VECTOR_DIR: str = "./data/vectors"

    # ---------- Embedding ----------
    EMBEDDING_PROVIDER: str = "hash"  # hash | api | local
    EMBEDDING_MODEL: str = "BAAI/bge-m3"
    EMBEDDING_DIM: int = 1024
    EMBEDDING_BATCH_SIZE: int = 64
    EMBEDDING_API_BASE: str = ""
    EMBEDDING_API_KEY: str = ""

    # ---------- LLM ----------
    LLM_PROVIDER: str = "mock"  # mock | deepseek | qwen | glm
    LLM_API_BASE: str = "https://api.deepseek.com/v1"
    LLM_API_KEY: str = ""
    LLM_MODEL: str = "deepseek-chat"
    LLM_TIMEOUT_SECONDS: float = 120.0
    LLM_MAX_RETRIES: int = 3
    LLM_CONCURRENCY: int = 4
    LLM_TEMPERATURE_GEN: float = 0.7
    LLM_TEMPERATURE_GRADE: float = 0.2
    LLM_TEMPERATURE_TUTOR: float = 0.6
    LLM_CIRCUIT_FAILURE_THRESHOLD: int = 3
    LLM_CIRCUIT_COOLDOWN_SECONDS: int = 60

    # ---------- RAG 参数 ----------
    # 分块边界策略：size（仅按字数，默认）/ heading（标题变更即断开）/ slide（换页即断开）
    # PPT 类课件建议 heading 或 slide：一页/一小节一个知识单元，避免同一知识点被切成多块
    CHUNK_BOUNDARY: str = "size"
    CHUNK_TARGET_CHARS: int = 600
    CHUNK_MAX_CHARS: int = 900
    CHUNK_MIN_CHARS: int = 120
    CHUNK_OVERLAP_CHARS: int = 100
    # 查询改写：把口语提问改写成课件术语（多一次 LLM 调用，约 1s），失败自动退回原查询
    QUERY_REWRITE_ENABLED: bool = False
    RETRIEVE_TOP_K: int = 6
    RETRIEVE_CANDIDATES: int = 20
    RRF_K: int = 60
    MIN_RETRIEVE_SCORE: float = 0.35
    # BM25 原始分无上界，用饱和度 K 做有界归一：raw/(raw+K)，避免"除以最大值"导致 top1 恒为 1
    BM25_SATURATION_K: float = 6.0
    # 查询有效词中"课程语料里从未出现"的占比超过该值 → 视为可能考纲外（需配合相关度判定）
    # 注意：多语言模型（bge-m3）能处理英文提问，仅凭词表会误杀，故必须与相关度联判
    MAX_UNKNOWN_TERM_RATIO: float = 0.5
    # 判为考纲外的相关度上限：未登录词多 且 最强证据相关度也低于此值 → 拒答
    OFF_SYLLABUS_RELEVANCE_FLOOR: float = 0.5
    CITATION_FUZZY_THRESHOLD: float = 0.85

    # ---------- 重排（两阶段检索的第二阶段） ----------
    # off（默认，只用 RRF 排序）| cross（交叉编码器本地推理）| llm（用现有大模型打分）
    RERANK_BACKEND: str = "off"
    RERANK_MODEL: str = "BAAI/bge-reranker-v2-m3"
    # 进入重排的候选数（太多会线性增加 CPU 推理耗时）
    RERANK_CANDIDATES: int = 20
    RERANK_BATCH_SIZE: int = 8
    # 候选文本截断长度：交叉编码器输入越长越慢，课程片段前 600 字通常已包含核心结论
    RERANK_MAX_CHARS: int = 600
    # 重排"有信息量"的最低分：交叉编码器对无关片段输出 sigmoid ≈ 0.5（logit≈0），
    # 若最高分都低于该值，说明模型认为"都不相关"，此时按分数排序只是噪声，
    # 应退回召回顺序；实测该阈值使口语类查询的 Hit@3 由 92.3% 恢复到 100%
    RERANK_MIN_INFORMATIVE_SCORE: float = 0.55

    # ---------- 业务约束 ----------
    MAX_UPLOAD_MB: int = 50
    MAX_GENERATE_COUNT: int = 20
    MAX_TUTOR_TURNS_PER_HOUR: int = 60
    MAX_QUESTION_REPAIR_ROUNDS: int = 2
    UPLOAD_DIR: str = "./data/uploads"

    # ---------- Prompt ----------
    PROMPT_VERSION: str = "v1"

    # ---------- 引导数据 ----------
    DEFAULT_ADMIN_USERNAME: str = "admin"
    DEFAULT_TEACHER_USERNAME: str = "teacher"
    DEFAULT_STUDENT_USERNAME: str = "student"
    DEFAULT_PASSWORD: str = "123456"

    @field_validator("SECRET_KEY")
    @classmethod
    def _check_secret(cls, v: str) -> str:
        if len(v) < 32:
            raise ValueError("SECRET_KEY 长度必须 >= 32 字符")
        return v

    @model_validator(mode="after")
    def _check_prod(self) -> Settings:
        if self.APP_ENV == "prod":
            if "dev-only" in self.SECRET_KEY:
                raise ValueError("生产环境必须设置独立的 SECRET_KEY")
            if self.LLM_PROVIDER != "mock" and not self.LLM_API_KEY:
                raise ValueError("LLM_PROVIDER 非 mock 时必须提供 LLM_API_KEY")
        if self.CHUNK_OVERLAP_CHARS >= self.CHUNK_TARGET_CHARS:
            raise ValueError("CHUNK_OVERLAP_CHARS 必须小于 CHUNK_TARGET_CHARS")
        if self.CHUNK_BOUNDARY not in ("size", "heading", "slide"):
            raise ValueError("CHUNK_BOUNDARY 只能是 size / heading / slide")
        return self

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]

    @property
    def max_upload_bytes(self) -> int:
        return self.MAX_UPLOAD_MB * 1024 * 1024

    @property
    def is_sqlite(self) -> bool:
        return self.DATABASE_URL.startswith("sqlite")

    def resolve_path(self, value: str) -> Path:
        p = Path(value)
        return p if p.is_absolute() else (PROJECT_DIR / p).resolve()


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings: Settings = get_settings()
