# 智评导学 —— 常用开发/部署命令
# 说明：`dev` 走 docker compose（需 Docker）；无 Docker 的环境用 `dev-local` 直接起本机进程。

SHELL := /bin/bash
COMPOSE := docker compose -f docker-compose.yml -f docker-compose.dev.yml
PY := python
VENV := .venv
ifeq ($(OS),Windows_NT)
	VENVBIN := $(VENV)/Scripts
else
	VENVBIN := $(VENV)/bin
endif
PYBIN := $(VENVBIN)/python

.PHONY: help install dev dev-local stop migrate seed api web test lint fmt build eval logs backup clean migrate-docker seed-docker ps

help:
	@echo "make install     安装后端(.venv)与前端依赖"
	@echo "make dev         启动 docker compose 全栈（pg/redis/api/worker/web）→ http://localhost:8080"
	@echo "make dev-local   无 Docker：本机起 api(8000) + web(5173)"
	@echo "make init        初始化数据库：migrate + seed --demo"
	@echo "make migrate     本机执行 alembic 迁移（Docker 场景用 migrate-docker）"
	@echo "make seed        本机写入演示数据（Docker 场景用 seed-docker）"
	@echo "make seed-docker 在 api 容器内写入演示数据"
	@echo "make ps          查看容器状态"
	@echo "make test        后端测试（pytest）"
	@echo "make lint        ruff 检查 + 前端类型检查"
	@echo "make build       前端生产构建"
	@echo "make eval        检索效果评测（输出 CSV 到 docs/experiments）"
	@echo "make backup      备份数据库到 backups/"
	@echo "make clean       清理构建产物与缓存"

install:
	$(PY) -m venv $(VENV)
	$(PYBIN) -m pip install -U pip
	$(PYBIN) -m pip install -e "backend[dev,agents]"
	cd frontend && npm install

dev:
	$(COMPOSE) up -d --build

dev-local:
	@echo "启动后端 http://127.0.0.1:8000/docs ，前端 http://127.0.0.1:5173"
	@( cd backend && $(abspath $(PYBIN)) -m uvicorn app.main:app --reload --port 8000 & \
	   cd frontend && npm run dev & wait )

stop:
	-$(COMPOSE) down

init: migrate seed

migrate:
	cd backend && $(abspath $(PYBIN)) -m alembic upgrade head

seed:
	cd backend && $(abspath $(PYBIN)) -m app.cli seed --demo

# Docker 场景：迁移由 compose 的 migrate 服务自动执行，数据用容器内 CLI 写入
seed-docker:
	docker compose exec -T api python -m app.cli seed --demo

migrate-docker:
	docker compose run --rm migrate

ps:
	docker compose ps

api:
	cd backend && $(abspath $(PYBIN)) -m uvicorn app.main:app --reload --port 8000

web:
	cd frontend && npm run dev

test:
	cd backend && $(abspath $(PYBIN)) -m pytest -q

lint:
	cd backend && $(abspath $(PYBIN)) -m ruff check app tests
	cd frontend && npx tsc --noEmit

fmt:
	cd backend && $(abspath $(PYBIN)) -m ruff check app tests --fix
	cd frontend && npx prettier --write "src/**/*.{ts,tsx,css}" 2>/dev/null || true

build:
	cd frontend && npm run build

eval:
	cd backend && $(abspath $(PYBIN)) -m app.cli eval-retrieval --course-id 1

logs:
	$(COMPOSE) logs -f api worker-io worker-llm

backup:
	mkdir -p backups
	$(COMPOSE) exec -T postgres pg_dump -U app course_agent > backups/course_agent_$$(date +%Y%m%d_%H%M).sql
	@echo "已备份到 backups/"

clean:
	rm -rf frontend/dist frontend/node_modules/.vite backend/.pytest_cache backend/.ruff_cache
	find backend -type d -name __pycache__ -prune -exec rm -rf {} + 2>/dev/null || true
