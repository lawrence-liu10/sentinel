-- Phase 1 schema: pgvector extension (for Phase 5 RAG) + the app tables.
-- Agent tables (incidents, agent_steps, ...) are created in Phase 4.

CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS orders (
    id         SERIAL PRIMARY KEY,
    item       TEXT NOT NULL,
    qty        INTEGER NOT NULL DEFAULT 1,
    status     TEXT NOT NULL DEFAULT 'pending',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS outbox (
    id         SERIAL PRIMARY KEY,
    order_id   INTEGER NOT NULL REFERENCES orders(id),
    event      TEXT NOT NULL,
    processed  BOOLEAN NOT NULL DEFAULT false,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS deploys (
    id          SERIAL PRIMARY KEY,
    service     TEXT NOT NULL,
    tag         TEXT NOT NULL,
    deployed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    actor       TEXT
);
