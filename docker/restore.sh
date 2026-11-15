#!/bin/bash
# Выполняется один раз при первом создании тома Postgres
set -e
pg_restore --no-owner --no-privileges \
  -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
  /backup/alfa_course_hackathon.backup
echo "Дамп восстановлен"