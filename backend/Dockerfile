# 后端多阶段构建：builder 编译依赖，runtime 只带运行产物（镜像体积更小、无编译工具链）
#
# 构建参数（一般不用改）：
#   EXTRAS       额外依赖组，默认 postgres+queue；需要 Chroma 时传 postgres,queue,vector
#   PIP_INDEX_URL 国内网络慢可换成镜像源，如 https://pypi.tuna.tsinghua.edu.cn/simple
FROM python:3.12-slim AS builder

ARG PIP_INDEX_URL=https://pypi.org/simple
ARG EXTRAS=postgres,queue

ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /build

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml ./
COPY app ./app
RUN python -m venv /opt/venv \
    && /opt/venv/bin/pip install -U pip \
    && /opt/venv/bin/pip install --index-url "${PIP_INDEX_URL}" ".[${EXTRAS}]"

FROM python:3.12-slim AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/opt/venv/bin:$PATH" \
    TZ=Asia/Shanghai

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl libpq5 procps \
    && rm -rf /var/lib/apt/lists/* \
    && useradd -m -u 10001 appuser

COPY --from=builder /opt/venv /opt/venv
WORKDIR /app
COPY --chown=appuser:appuser . .

# 挂载点由编排层提供（宿主机 ./data）；镜像内也建好，便于单容器直接跑
RUN mkdir -p /data/uploads /data/vectors && chown -R appuser:appuser /data
USER appuser

EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=5s --start-period=30s --retries=5 \
    CMD curl -fsS http://127.0.0.1:8000/health || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]
