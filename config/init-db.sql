-- RFC-612: Create multiple databases for different purposes
-- Separate databases by logical purpose for lifecycle isolation, backup granularity,
-- and pgvector extension requirements.

-- Database: soothe_checkpoints (LangGraph + AgentLoop checkpoints - IG-055 shared database)
SELECT 'CREATE DATABASE soothe_checkpoints'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'soothe_checkpoints')\gexec

-- Database: soothe_metadata (Thread metadata - DurabilityProtocol)
SELECT 'CREATE DATABASE soothe_metadata'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'soothe_metadata')\gexec

-- Database: soothe_vectors (pgvector embeddings)
-- This database will have the pgvector extension installed
SELECT 'CREATE DATABASE soothe_vectors'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'soothe_vectors')\gexec

-- Database: soothe_memory (MemU long-term memory)
SELECT 'CREATE DATABASE soothe_memory'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'soothe_memory')\gexec

-- Install pgvector extension in soothe_vectors database
\c soothe_vectors
CREATE EXTENSION IF NOT EXISTS vector;

-- Note: soothe_checkpoints will have AgentLoop tables created automatically by
-- PostgreSQLPersistenceBackend when AgentLoop initializes (IG-055)
