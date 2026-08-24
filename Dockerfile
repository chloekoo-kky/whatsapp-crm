# Clinic CRM — Django app
FROM node:22-bookworm-slim AS frontend

WORKDIR /app

COPY package.json package-lock.json ./
COPY tailwind.config.js ./
COPY theme ./theme
COPY leads ./leads

RUN npm ci && npm run build:css

FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

RUN apt-get update \
  && apt-get install -y --no-install-recommends libpq5 \
  && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
COPY --from=frontend /app/leads/static/leads/css/app.css /app/leads/static/leads/css/app.css

# Windows CRLF in shell scripts breaks the shebang in Linux ("no such file or directory").
RUN sed -i 's/\r$//' docker/entrypoint.sh \
  && chmod +x docker/entrypoint.sh

ARG DJANGO_SECRET_KEY=docker-build-collectstatic-only
ENV DJANGO_SECRET_KEY=${DJANGO_SECRET_KEY}
RUN python manage.py collectstatic --noinput

EXPOSE 8000

ENTRYPOINT ["/bin/sh", "/app/docker/entrypoint.sh"]
