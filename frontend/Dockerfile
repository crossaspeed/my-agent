# 前端生产镜像：Node 构建 → Nginx 托管静态资源并反代 /api（SSE 必须关闭缓冲）
#
# 构建参数：
#   NPM_REGISTRY 国内网络慢可换镜像源，如 https://registry.npmmirror.com
FROM node:22-alpine AS builder

ARG NPM_REGISTRY=

WORKDIR /app
COPY package.json package-lock.json* ./
RUN if [ -n "$NPM_REGISTRY" ]; then npm config set registry "$NPM_REGISTRY"; fi \
    && (npm ci || npm install)
COPY . .
RUN npm run build

FROM nginx:1.27-alpine AS runtime

RUN rm -f /etc/nginx/conf.d/default.conf
COPY nginx.conf /etc/nginx/conf.d/app.conf
COPY --from=builder /app/dist /usr/share/nginx/html

EXPOSE 80
HEALTHCHECK --interval=15s --timeout=3s --retries=5 CMD wget -qO- http://127.0.0.1/ >/dev/null || exit 1
CMD ["nginx", "-g", "daemon off;"]
