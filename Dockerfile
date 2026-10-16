FROM node:22-bookworm-slim AS web
WORKDIR /build
RUN corepack enable && corepack prepare pnpm@11.25.0 --activate
COPY apps/web/package.json apps/web/pnpm-lock.yaml apps/web/pnpm-workspace.yaml ./
RUN pnpm install --frozen-lockfile
COPY apps/web/ ./
RUN pnpm build

FROM python:3.12-slim
WORKDIR /app
ENV PYTHONUNBUFFERED=1 CIVIC_DATA_DIR=/app/data
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY services/ ./services/
COPY database/ ./database/
COPY scripts/ ./scripts/
COPY --from=web /build/dist ./apps/web/dist
RUN useradd --create-home civic && mkdir -p /app/data && chown -R civic:civic /app
USER civic
EXPOSE 8000
CMD ["python", "scripts/run.py", "--host", "0.0.0.0"]
