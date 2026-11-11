# 后端多阶段构建：builder 编译依赖，runtime 只带运行产物（镜像体积更小、无编译工具链）
#
# 构建参数（一般不用改）：
#   EXTRAS          额外依赖组，默认 postgres+queue+embedding（含 bge-m3 所需 runtime）
#                   只要最简部署时可传 postgres,queue 省掉 torch
#   PIP_INDEX_URL   国内网络慢可换镜像源，如 https://pypi.tuna.tsinghua.edu.cn/simple
#   TORCH_INDEX_URL torch 轮子索引；默认 CPU 版（关键：用官方默认源会拉 CUDA 依赖，镜像 +3GB）
FROM python:3.12-slim AS builder

ARG PIP_INDEX_URL=https://pypi.org/simple
ARG TORCH_INDEX_URL=https://download.pytorch.org/whl/cpu
ARG EXTRAS=postgres,queue,embedding

ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /build

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml ./
COPY app ./app
# 先装 CPU 版 torch，再装其余依赖：sentence-transformers 会复用已安装的 torch，
# 不会再去 PyPI 拉带 CUDA 的完整包（否则镜像会多出 3GB 且构建极慢）。
RUN python -m venv /opt/venv \
    && /opt/venv/bin/pip install -U pip \
    && case ",${EXTRAS}," in \
         *,embedding,*) /opt/venv/bin/pip install --index-url "${TORCH_INDEX_URL}" torch ;; \
       esac \
    && /opt/venv/bin/pip install --index-url "${PIP_INDEX_URL}" ".[${EXTRAS}]"

FROM python:3.12-slim AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/opt/venv/bin:$PATH" \
    TZ=Asia/Shanghai \
    HF_HOME=/models/hf \
    HF_HUB_DISABLE_TELEMETRY=1 \
    SENTENCE_TRANSFORMERS_HOME=/models/st \
    TOKENIZERS_PARALLELISM=false

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl libpq5 procps \
    && rm -rf /var/lib/apt/lists/* \
    && useradd -m -u 10001 appuser

COPY --from=builder /opt/venv /opt/venv
WORKDIR /app
COPY --chown=appuser:appuser . .

# 挂载点由编排层提供（宿主机 ./data）；镜像内也建好，便于单容器直接跑
# /models 持久化 bge-m3 权重，避免每次重建容器都重新下载 2GB+
RUN mkdir -p /data/uploads /data/vectors /models/hf /models/st \
    && chown -R appuser:appuser /data /models
USER appuser

EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=5s --start-period=30s --retries=5 \
    CMD curl -fsS http://127.0.0.1:8000/health || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]
