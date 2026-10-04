# The runtime serves prebuilt HTML, JSON and Markdown. No keys or Python in this image.
FROM node:22-alpine AS build
WORKDIR /app
ENV ASTRO_TELEMETRY_DISABLED=1
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY astro.config.mjs tsconfig.json ./
COPY src ./src
COPY public ./public
COPY data ./data
ARG POLITRACE_DATASET=auto
ENV POLITRACE_DATASET=$POLITRACE_DATASET
RUN npm run build

FROM nginxinc/nginx-unprivileged:1.28-alpine AS runtime
COPY deploy/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
USER 101
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD wget -q -O /dev/null http://127.0.0.1:8080/api/health.json || exit 1
