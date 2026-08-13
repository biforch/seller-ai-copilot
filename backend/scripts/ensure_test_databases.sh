#!/usr/bin/env bash
set -euo pipefail

BASE_URL="${TEST_DATABASE_ADMIN_URL:-postgresql://localhost:5432/postgres}"
MIGRATION_DB="${MIGRATION_TEST_DATABASE:-sellerai_migration_test}"
APP_TEST_DB="${APP_TEST_DATABASE:-sellerai_test}"
SELLERAI_URL="${SELLERAI_ADMIN_URL:-postgresql://sellerai:sellerai123@localhost:5432/postgres}"

psql "$BASE_URL" -tc "SELECT 1 FROM pg_database WHERE datname='${MIGRATION_DB}'" | grep -q 1 \
  || psql "$BASE_URL" -c "CREATE DATABASE ${MIGRATION_DB} OWNER sellerai;"

psql "$BASE_URL" -tc "SELECT 1 FROM pg_database WHERE datname='${APP_TEST_DB}'" | grep -q 1 \
  || psql "$BASE_URL" -c "CREATE DATABASE ${APP_TEST_DB} OWNER sellerai;"

psql "$BASE_URL" -c "GRANT ALL PRIVILEGES ON DATABASE ${MIGRATION_DB} TO sellerai;" || true
psql "$BASE_URL" -c "GRANT ALL PRIVILEGES ON DATABASE ${APP_TEST_DB} TO sellerai;" || true

for db in "${MIGRATION_DB}" "${APP_TEST_DB}"; do
  psql "postgresql://sellerai:sellerai123@localhost:5432/${db}" -c "ALTER SCHEMA public OWNER TO sellerai;" || true
  psql "postgresql://sellerai:sellerai123@localhost:5432/${db}" -c "GRANT ALL ON SCHEMA public TO sellerai;" || true
done

echo "Ensured test databases: ${MIGRATION_DB}, ${APP_TEST_DB}"
