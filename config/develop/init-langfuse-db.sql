-- Development only: Langfuse v3 PostgreSQL database on shared soothe-pgvector.
-- Mounted from docker-compose.yml (dev stack). Not used in production deploy/.
--
-- Soothe application databases (soothe_checkpoints, soothe_metadata, soothe_vectors,
-- soothe_memory) are auto-provisioned on daemon/worker startup via postgres_provisioning.

SELECT 'CREATE DATABASE langfuse'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'langfuse')\gexec
