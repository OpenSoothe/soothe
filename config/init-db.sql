-- Create the soothe database used by persistence backends.
-- The default vectordb database is created by POSTGRES_DB env var.
SELECT 'CREATE DATABASE soothe'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'soothe')\gexec
