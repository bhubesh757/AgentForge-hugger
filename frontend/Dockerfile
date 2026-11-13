# syntax=docker/dockerfile:1.7
# AgentForge AI — frontend image (build context: ./frontend)
# Stage 1: build the Vite SPA with pnpm. Stage 2: serve dist/ with unprivileged nginx.

ARG NODE_VERSION=22
FROM node:${NODE_VERSION}-alpine AS build
WORKDIR /app
ENV PNPM_HOME=/pnpm PATH=/pnpm:$PATH CI=true
ARG PNPM_VERSION=12.18.0
RUN npm install -g pnpm@${PNPM_VERSION} && pnpm config set store-dir /pnpm/store

# Install dependencies first (cached layer)
COPY package.json pnpm-lock.yaml ./
RUN --mount=type=cache,id=pnpm-store,target=/pnpm/store \
    pnpm install --frozen-lockfile

# Build-time configuration (Vite inlines VITE_* at build time; never put secrets here)
ARG VITE_API_BASE_URL=http://localhost:8000/api/v1
ARG VITE_DEMO_MODE=false
ARG VITE_BASE_PATH=/
ARG VITE_ROUTER_MODE=browser
ENV VITE_API_BASE_URL=${VITE_API_BASE_URL} \
    VITE_DEMO_MODE=${VITE_DEMO_MODE} \
    VITE_BASE_PATH=${VITE_BASE_PATH} \
    VITE_ROUTER_MODE=${VITE_ROUTER_MODE}

COPY . .
RUN pnpm build

# ---------------------------------------------------------------------------
FROM nginxinc/nginx-unprivileged:1.27-alpine AS runtime
LABEL org.opencontainers.image.title="agentforge-ai-frontend" \
      org.opencontainers.image.source="https://github.com/OWNER/agentforge-ai" \
      org.opencontainers.image.licenses="MIT"

COPY --chown=nginx:nginx nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build --chown=nginx:nginx /app/dist /usr/share/nginx/html

USER nginx
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
  CMD wget -q -O /dev/null http://127.0.0.1:8080/healthz || exit 1
