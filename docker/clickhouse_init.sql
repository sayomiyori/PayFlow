CREATE DATABASE IF NOT EXISTS payflow_analytics;

CREATE TABLE IF NOT EXISTS payflow_analytics.payment_events
(
    merchant_id String,
    payment_id String,
    event_type String,
    amount Decimal(12, 2),
    currency LowCardinality(String),
    status LowCardinality(String),
    created_at DateTime
)
ENGINE = MergeTree
PARTITION BY toYYYYMM(created_at)
ORDER BY (merchant_id, created_at, payment_id);

ALTER TABLE payflow_analytics.payment_events
    ADD INDEX IF NOT EXISTS bf_merchant_id merchant_id TYPE bloom_filter(0.01) GRANULARITY 1;