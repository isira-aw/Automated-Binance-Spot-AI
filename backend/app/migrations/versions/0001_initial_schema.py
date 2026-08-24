"""Initial schema — full table set for the Tier 1 + Tier 2 roadmap.

The complete table list from MASTER PROMPT §3 is created up front so that later
phases add data, not structural churn.  Tables belonging to unbuilt phases stay
empty until their engine exists — the system never writes fabricated rows (§96).

Revision ID: 0001_initial_schema
Revises:
Create Date: 2026-08-24
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001_initial_schema"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table('assets',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('symbol', sa.String(length=32), nullable=False),
    sa.Column('base_asset', sa.String(length=16), nullable=False),
    sa.Column('quote_asset', sa.String(length=16), nullable=False),
    sa.Column('enabled', sa.Boolean(), nullable=False),
    sa.Column('status', sa.String(length=32), nullable=True),
    sa.Column('filters', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('filters_updated_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_assets'))
    )
    op.create_index(op.f('ix_assets_symbol'), 'assets', ['symbol'], unique=True)
    op.create_table('audit_logs',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('timestamp', sa.DateTime(timezone=True), nullable=False),
    sa.Column('actor', sa.String(length=64), nullable=False),
    sa.Column('action', sa.String(length=64), nullable=False),
    sa.Column('symbol', sa.String(length=32), nullable=True),
    sa.Column('timeframe', sa.String(length=8), nullable=True),
    sa.Column('signal_id', sa.Integer(), nullable=True),
    sa.Column('trade_id', sa.Integer(), nullable=True),
    sa.Column('strategy_version', sa.String(length=32), nullable=True),
    sa.Column('model_version', sa.String(length=64), nullable=True),
    sa.Column('payload', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_audit_logs'))
    )
    op.create_index(op.f('ix_audit_logs_model_version'), 'audit_logs', ['model_version'], unique=False)
    op.create_index(op.f('ix_audit_logs_signal_id'), 'audit_logs', ['signal_id'], unique=False)
    op.create_index(op.f('ix_audit_logs_strategy_version'), 'audit_logs', ['strategy_version'], unique=False)
    op.create_index(op.f('ix_audit_logs_symbol'), 'audit_logs', ['symbol'], unique=False)
    op.create_index(op.f('ix_audit_logs_timestamp'), 'audit_logs', ['timestamp'], unique=False)
    op.create_index(op.f('ix_audit_logs_trade_id'), 'audit_logs', ['trade_id'], unique=False)
    op.create_table('backtest_runs',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('job_id', sa.String(length=64), nullable=False),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('symbols', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('timeframe', sa.String(length=8), nullable=False),
    sa.Column('range_start', sa.DateTime(timezone=True), nullable=False),
    sa.Column('range_end', sa.DateTime(timezone=True), nullable=False),
    sa.Column('initial_capital', sa.Numeric(precision=24, scale=10), nullable=False),
    sa.Column('maker_fee', sa.Numeric(precision=10, scale=6), nullable=False),
    sa.Column('taker_fee', sa.Numeric(precision=10, scale=6), nullable=False),
    sa.Column('slippage_bps', sa.Numeric(precision=10, scale=4), nullable=False),
    sa.Column('strategy_version', sa.String(length=32), nullable=False),
    sa.Column('model_version', sa.String(length=64), nullable=True),
    sa.Column('feature_version', sa.String(length=32), nullable=True),
    sa.Column('config', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('metrics', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('assumptions', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('artifact_path', sa.Text(), nullable=True),
    sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('error', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_backtest_runs'))
    )
    op.create_index(op.f('ix_backtest_runs_job_id'), 'backtest_runs', ['job_id'], unique=True)
    op.create_index(op.f('ix_backtest_runs_model_version'), 'backtest_runs', ['model_version'], unique=False)
    op.create_index(op.f('ix_backtest_runs_status'), 'backtest_runs', ['status'], unique=False)
    op.create_index(op.f('ix_backtest_runs_strategy_version'), 'backtest_runs', ['strategy_version'], unique=False)
    op.create_table('candles',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('symbol', sa.String(length=32), nullable=False),
    sa.Column('timeframe', sa.String(length=8), nullable=False),
    sa.Column('open_time', sa.DateTime(timezone=True), nullable=False),
    sa.Column('close_time', sa.DateTime(timezone=True), nullable=False),
    sa.Column('open', sa.Numeric(precision=24, scale=10), nullable=False),
    sa.Column('high', sa.Numeric(precision=24, scale=10), nullable=False),
    sa.Column('low', sa.Numeric(precision=24, scale=10), nullable=False),
    sa.Column('close', sa.Numeric(precision=24, scale=10), nullable=False),
    sa.Column('volume', sa.Numeric(precision=28, scale=10), nullable=False),
    sa.Column('quote_volume', sa.Numeric(precision=28, scale=10), nullable=True),
    sa.Column('trades', sa.Integer(), nullable=True),
    sa.Column('is_closed', sa.Boolean(), nullable=False),
    sa.Column('source', sa.String(length=32), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_candles')),
    sa.UniqueConstraint('symbol', 'timeframe', 'open_time', name='uq_candles_symbol')
    )
    op.create_table('exchange_settings',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('exchange', sa.String(length=32), nullable=False),
    sa.Column('testnet', sa.Boolean(), nullable=False),
    sa.Column('maker_fee', sa.Numeric(precision=10, scale=6), nullable=False),
    sa.Column('taker_fee', sa.Numeric(precision=10, scale=6), nullable=False),
    sa.Column('rate_limits', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('server_time_offset_ms', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_exchange_settings')),
    sa.UniqueConstraint('exchange', 'testnet', name='uq_exchange_settings_exchange')
    )
    op.create_table('execution_events',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('timestamp', sa.DateTime(timezone=True), nullable=False),
    sa.Column('venue', sa.String(length=24), nullable=False),
    sa.Column('symbol', sa.String(length=32), nullable=False),
    sa.Column('state', sa.String(length=32), nullable=False),
    sa.Column('previous_state', sa.String(length=32), nullable=True),
    sa.Column('signal_id', sa.Integer(), nullable=True),
    sa.Column('order_id', sa.Integer(), nullable=True),
    sa.Column('position_id', sa.Integer(), nullable=True),
    sa.Column('trade_id', sa.Integer(), nullable=True),
    sa.Column('details', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_execution_events'))
    )
    op.create_index(op.f('ix_execution_events_order_id'), 'execution_events', ['order_id'], unique=False)
    op.create_index(op.f('ix_execution_events_position_id'), 'execution_events', ['position_id'], unique=False)
    op.create_index(op.f('ix_execution_events_signal_id'), 'execution_events', ['signal_id'], unique=False)
    op.create_index(op.f('ix_execution_events_symbol'), 'execution_events', ['symbol'], unique=False)
    op.create_index(op.f('ix_execution_events_timestamp'), 'execution_events', ['timestamp'], unique=False)
    op.create_index(op.f('ix_execution_events_trade_id'), 'execution_events', ['trade_id'], unique=False)
    op.create_table('live_orders',
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('client_order_id', sa.String(length=64), nullable=False),
    sa.Column('exchange_order_id', sa.String(length=64), nullable=True),
    sa.Column('signal_id', sa.Integer(), nullable=True),
    sa.Column('symbol', sa.String(length=32), nullable=False),
    sa.Column('side', sa.String(length=8), nullable=False),
    sa.Column('order_type', sa.String(length=24), nullable=False),
    sa.Column('status', sa.String(length=24), nullable=False),
    sa.Column('quantity', sa.Numeric(precision=28, scale=12), nullable=False),
    sa.Column('price', sa.Numeric(precision=24, scale=10), nullable=True),
    sa.Column('filled_quantity', sa.Numeric(precision=28, scale=12), nullable=False),
    sa.Column('average_fill_price', sa.Numeric(precision=24, scale=10), nullable=True),
    sa.Column('fee', sa.Numeric(precision=24, scale=10), nullable=False),
    sa.Column('fee_asset', sa.String(length=16), nullable=True),
    sa.Column('slippage', sa.Numeric(precision=18, scale=10), nullable=True),
    sa.Column('submitted_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at_exchange', sa.DateTime(timezone=True), nullable=True),
    sa.Column('strategy_version', sa.String(length=32), nullable=True),
    sa.Column('rejection_reason', sa.Text(), nullable=True),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_live_orders')),
    sa.UniqueConstraint('client_order_id', name='uq_live_orders_client_order_id')
    )
    op.create_index(op.f('ix_live_orders_client_order_id'), 'live_orders', ['client_order_id'], unique=False)
    op.create_index(op.f('ix_live_orders_exchange_order_id'), 'live_orders', ['exchange_order_id'], unique=False)
    op.create_index(op.f('ix_live_orders_signal_id'), 'live_orders', ['signal_id'], unique=False)
    op.create_index(op.f('ix_live_orders_status'), 'live_orders', ['status'], unique=False)
    op.create_index(op.f('ix_live_orders_symbol'), 'live_orders', ['symbol'], unique=False)
    op.create_table('live_positions',
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('symbol', sa.String(length=32), nullable=False),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('quantity', sa.Numeric(precision=28, scale=12), nullable=False),
    sa.Column('entry_price', sa.Numeric(precision=24, scale=10), nullable=False),
    sa.Column('entry_time', sa.DateTime(timezone=True), nullable=False),
    sa.Column('exit_price', sa.Numeric(precision=24, scale=10), nullable=True),
    sa.Column('exit_time', sa.DateTime(timezone=True), nullable=True),
    sa.Column('stop_loss', sa.Numeric(precision=24, scale=10), nullable=True),
    sa.Column('take_profit', sa.Numeric(precision=24, scale=10), nullable=True),
    sa.Column('trailing_stop', sa.Numeric(precision=24, scale=10), nullable=True),
    sa.Column('unrealised_pnl', sa.Numeric(precision=24, scale=10), nullable=True),
    sa.Column('realised_pnl', sa.Numeric(precision=24, scale=10), nullable=True),
    sa.Column('fees_paid', sa.Numeric(precision=24, scale=10), nullable=False),
    sa.Column('signal_id', sa.Integer(), nullable=True),
    sa.Column('strategy_version', sa.String(length=32), nullable=True),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_live_positions'))
    )
    op.create_index(op.f('ix_live_positions_signal_id'), 'live_positions', ['signal_id'], unique=False)
    op.create_index(op.f('ix_live_positions_status'), 'live_positions', ['status'], unique=False)
    op.create_index(op.f('ix_live_positions_symbol'), 'live_positions', ['symbol'], unique=False)
    op.create_table('macro_events',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('event_type', sa.String(length=64), nullable=False),
    sa.Column('scheduled_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('provider', sa.String(length=64), nullable=False),
    sa.Column('title', sa.Text(), nullable=False),
    sa.Column('importance', sa.Numeric(precision=6, scale=4), nullable=True),
    sa.Column('actual', sa.String(length=64), nullable=True),
    sa.Column('forecast', sa.String(length=64), nullable=True),
    sa.Column('previous', sa.String(length=64), nullable=True),
    sa.Column('details', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_macro_events'))
    )
    op.create_index(op.f('ix_macro_events_event_type'), 'macro_events', ['event_type'], unique=False)
    op.create_index(op.f('ix_macro_events_scheduled_at'), 'macro_events', ['scheduled_at'], unique=False)
    op.create_table('market_data_metadata',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('symbol', sa.String(length=32), nullable=False),
    sa.Column('timeframe', sa.String(length=8), nullable=False),
    sa.Column('source', sa.String(length=32), nullable=False),
    sa.Column('first_candle_open', sa.DateTime(timezone=True), nullable=True),
    sa.Column('last_candle_open', sa.DateTime(timezone=True), nullable=True),
    sa.Column('candle_count', sa.Integer(), nullable=False),
    sa.Column('missing_candles', sa.Integer(), nullable=False),
    sa.Column('last_integrity_check', sa.DateTime(timezone=True), nullable=True),
    sa.Column('integrity_report', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_market_data_metadata')),
    sa.UniqueConstraint('symbol', 'timeframe', 'source', name='uq_market_data_metadata_symbol')
    )
    op.create_index(op.f('ix_market_data_metadata_symbol'), 'market_data_metadata', ['symbol'], unique=False)
    op.create_table('market_regimes',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('symbol', sa.String(length=32), nullable=False),
    sa.Column('timeframe', sa.String(length=8), nullable=False),
    sa.Column('open_time', sa.DateTime(timezone=True), nullable=False),
    sa.Column('regime', sa.String(length=32), nullable=False),
    sa.Column('confidence', sa.Numeric(precision=6, scale=4), nullable=False),
    sa.Column('detector_version', sa.String(length=32), nullable=False),
    sa.Column('details', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_market_regimes')),
    sa.UniqueConstraint('symbol', 'timeframe', 'open_time', 'detector_version', name='uq_market_regimes_symbol')
    )
    op.create_index(op.f('ix_market_regimes_open_time'), 'market_regimes', ['open_time'], unique=False)
    op.create_index(op.f('ix_market_regimes_symbol'), 'market_regimes', ['symbol'], unique=False)
    op.create_table('model_metrics',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('model_version', sa.String(length=64), nullable=False),
    sa.Column('evaluated_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('window_start', sa.DateTime(timezone=True), nullable=True),
    sa.Column('window_end', sa.DateTime(timezone=True), nullable=True),
    sa.Column('metric_set', sa.String(length=32), nullable=False),
    sa.Column('metrics', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_model_metrics'))
    )
    op.create_index(op.f('ix_model_metrics_model_version'), 'model_metrics', ['model_version'], unique=False)
    op.create_table('model_predictions',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('model_id', sa.String(length=64), nullable=False),
    sa.Column('model_version', sa.String(length=64), nullable=False),
    sa.Column('feature_version', sa.String(length=32), nullable=False),
    sa.Column('symbol', sa.String(length=32), nullable=False),
    sa.Column('timeframe', sa.String(length=8), nullable=False),
    sa.Column('open_time', sa.DateTime(timezone=True), nullable=False),
    sa.Column('predicted_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('prob_up', sa.Numeric(precision=8, scale=6), nullable=False),
    sa.Column('prob_neutral', sa.Numeric(precision=8, scale=6), nullable=False),
    sa.Column('prob_down', sa.Numeric(precision=8, scale=6), nullable=False),
    sa.Column('fusion_score', sa.Numeric(precision=6, scale=4), nullable=False),
    sa.Column('confidence', sa.Numeric(precision=6, scale=4), nullable=False),
    sa.Column('shadow_mode', sa.Boolean(), nullable=False),
    sa.Column('realised_label', sa.Integer(), nullable=True),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_model_predictions')),
    sa.UniqueConstraint('model_version', 'symbol', 'timeframe', 'open_time', name='uq_model_predictions_model_version')
    )
    op.create_index(op.f('ix_model_predictions_model_version'), 'model_predictions', ['model_version'], unique=False)
    op.create_index(op.f('ix_model_predictions_predicted_at'), 'model_predictions', ['predicted_at'], unique=False)
    op.create_index('ix_model_predictions_symbol_time', 'model_predictions', ['symbol', 'predicted_at'], unique=False)
    op.create_table('model_versions',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('model_id', sa.String(length=64), nullable=False),
    sa.Column('version', sa.String(length=64), nullable=False),
    sa.Column('model_type', sa.String(length=32), nullable=False),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('symbol', sa.String(length=32), nullable=True),
    sa.Column('timeframe', sa.String(length=8), nullable=True),
    sa.Column('feature_version', sa.String(length=32), nullable=False),
    sa.Column('artifact_path', sa.Text(), nullable=False),
    sa.Column('artifact_sha256', sa.String(length=64), nullable=True),
    sa.Column('preprocessing_path', sa.Text(), nullable=True),
    sa.Column('training_data_range', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('validation_range', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('test_range', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('hyperparameters', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('metrics', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('promoted_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('notes', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_model_versions')),
    sa.UniqueConstraint('model_id', 'version', name='uq_model_versions_model_id')
    )
    op.create_index(op.f('ix_model_versions_model_id'), 'model_versions', ['model_id'], unique=False)
    op.create_index(op.f('ix_model_versions_status'), 'model_versions', ['status'], unique=False)
    op.create_index(op.f('ix_model_versions_symbol'), 'model_versions', ['symbol'], unique=False)
    op.create_table('news_articles',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('external_id', sa.String(length=255), nullable=False),
    sa.Column('provider', sa.String(length=64), nullable=False),
    sa.Column('published_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('headline', sa.Text(), nullable=False),
    sa.Column('url', sa.Text(), nullable=True),
    sa.Column('body', sa.Text(), nullable=True),
    sa.Column('symbol', sa.String(length=32), nullable=True),
    sa.Column('category', sa.String(length=64), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_news_articles')),
    sa.UniqueConstraint('provider', 'external_id', name='uq_news_articles_provider')
    )
    op.create_index(op.f('ix_news_articles_published_at'), 'news_articles', ['published_at'], unique=False)
    op.create_index(op.f('ix_news_articles_symbol'), 'news_articles', ['symbol'], unique=False)
    op.create_table('paper_orders',
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('client_order_id', sa.String(length=64), nullable=False),
    sa.Column('exchange_order_id', sa.String(length=64), nullable=True),
    sa.Column('signal_id', sa.Integer(), nullable=True),
    sa.Column('symbol', sa.String(length=32), nullable=False),
    sa.Column('side', sa.String(length=8), nullable=False),
    sa.Column('order_type', sa.String(length=24), nullable=False),
    sa.Column('status', sa.String(length=24), nullable=False),
    sa.Column('quantity', sa.Numeric(precision=28, scale=12), nullable=False),
    sa.Column('price', sa.Numeric(precision=24, scale=10), nullable=True),
    sa.Column('filled_quantity', sa.Numeric(precision=28, scale=12), nullable=False),
    sa.Column('average_fill_price', sa.Numeric(precision=24, scale=10), nullable=True),
    sa.Column('fee', sa.Numeric(precision=24, scale=10), nullable=False),
    sa.Column('fee_asset', sa.String(length=16), nullable=True),
    sa.Column('slippage', sa.Numeric(precision=18, scale=10), nullable=True),
    sa.Column('submitted_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at_exchange', sa.DateTime(timezone=True), nullable=True),
    sa.Column('strategy_version', sa.String(length=32), nullable=True),
    sa.Column('rejection_reason', sa.Text(), nullable=True),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_paper_orders')),
    sa.UniqueConstraint('client_order_id', name='uq_paper_orders_client_order_id')
    )
    op.create_index(op.f('ix_paper_orders_client_order_id'), 'paper_orders', ['client_order_id'], unique=False)
    op.create_index(op.f('ix_paper_orders_exchange_order_id'), 'paper_orders', ['exchange_order_id'], unique=False)
    op.create_index(op.f('ix_paper_orders_signal_id'), 'paper_orders', ['signal_id'], unique=False)
    op.create_index(op.f('ix_paper_orders_status'), 'paper_orders', ['status'], unique=False)
    op.create_index(op.f('ix_paper_orders_symbol'), 'paper_orders', ['symbol'], unique=False)
    op.create_table('paper_positions',
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('symbol', sa.String(length=32), nullable=False),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('quantity', sa.Numeric(precision=28, scale=12), nullable=False),
    sa.Column('entry_price', sa.Numeric(precision=24, scale=10), nullable=False),
    sa.Column('entry_time', sa.DateTime(timezone=True), nullable=False),
    sa.Column('exit_price', sa.Numeric(precision=24, scale=10), nullable=True),
    sa.Column('exit_time', sa.DateTime(timezone=True), nullable=True),
    sa.Column('stop_loss', sa.Numeric(precision=24, scale=10), nullable=True),
    sa.Column('take_profit', sa.Numeric(precision=24, scale=10), nullable=True),
    sa.Column('trailing_stop', sa.Numeric(precision=24, scale=10), nullable=True),
    sa.Column('unrealised_pnl', sa.Numeric(precision=24, scale=10), nullable=True),
    sa.Column('realised_pnl', sa.Numeric(precision=24, scale=10), nullable=True),
    sa.Column('fees_paid', sa.Numeric(precision=24, scale=10), nullable=False),
    sa.Column('signal_id', sa.Integer(), nullable=True),
    sa.Column('strategy_version', sa.String(length=32), nullable=True),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_paper_positions'))
    )
    op.create_index(op.f('ix_paper_positions_signal_id'), 'paper_positions', ['signal_id'], unique=False)
    op.create_index(op.f('ix_paper_positions_status'), 'paper_positions', ['status'], unique=False)
    op.create_index(op.f('ix_paper_positions_symbol'), 'paper_positions', ['symbol'], unique=False)
    op.create_table('pattern_statistics',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('pattern_type', sa.String(length=64), nullable=False),
    sa.Column('symbol', sa.String(length=32), nullable=True),
    sa.Column('timeframe', sa.String(length=8), nullable=False),
    sa.Column('detector_version', sa.String(length=32), nullable=False),
    sa.Column('sample_size', sa.Integer(), nullable=False),
    sa.Column('in_sample_range', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('out_of_sample_range', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('win_rate', sa.Numeric(precision=8, scale=5), nullable=True),
    sa.Column('expected_return', sa.Numeric(precision=18, scale=8), nullable=True),
    sa.Column('profit_factor', sa.Numeric(precision=12, scale=5), nullable=True),
    sa.Column('sharpe', sa.Numeric(precision=12, scale=5), nullable=True),
    sa.Column('max_drawdown', sa.Numeric(precision=12, scale=5), nullable=True),
    sa.Column('mae', sa.Numeric(precision=18, scale=8), nullable=True),
    sa.Column('mfe', sa.Numeric(precision=18, scale=8), nullable=True),
    sa.Column('verdict', sa.String(length=16), nullable=False),
    sa.Column('notes', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_pattern_statistics')),
    sa.UniqueConstraint('pattern_type', 'symbol', 'timeframe', 'detector_version', name='uq_pattern_statistics_pattern_type')
    )
    op.create_index(op.f('ix_pattern_statistics_pattern_type'), 'pattern_statistics', ['pattern_type'], unique=False)
    op.create_index(op.f('ix_pattern_statistics_symbol'), 'pattern_statistics', ['symbol'], unique=False)
    op.create_table('patterns',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('symbol', sa.String(length=32), nullable=False),
    sa.Column('timeframe', sa.String(length=8), nullable=False),
    sa.Column('pattern_type', sa.String(length=64), nullable=False),
    sa.Column('detector_version', sa.String(length=32), nullable=False),
    sa.Column('start_time', sa.DateTime(timezone=True), nullable=False),
    sa.Column('end_time', sa.DateTime(timezone=True), nullable=False),
    sa.Column('direction', sa.String(length=16), nullable=False),
    sa.Column('confidence', sa.Numeric(precision=6, scale=4), nullable=False),
    sa.Column('details', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('outcome_return', sa.Numeric(precision=18, scale=8), nullable=True),
    sa.Column('outcome_evaluated_at', sa.DateTime(timezone=True), nullable=True),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_patterns'))
    )
    op.create_index(op.f('ix_patterns_end_time'), 'patterns', ['end_time'], unique=False)
    op.create_index(op.f('ix_patterns_pattern_type'), 'patterns', ['pattern_type'], unique=False)
    op.create_index(op.f('ix_patterns_symbol'), 'patterns', ['symbol'], unique=False)
    op.create_index('ix_patterns_symbol_type_end', 'patterns', ['symbol', 'pattern_type', 'end_time'], unique=False)
    op.create_table('portfolio_snapshots',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('venue', sa.String(length=24), nullable=False),
    sa.Column('timestamp', sa.DateTime(timezone=True), nullable=False),
    sa.Column('quote_balance', sa.Numeric(precision=24, scale=10), nullable=False),
    sa.Column('positions_value', sa.Numeric(precision=24, scale=10), nullable=False),
    sa.Column('equity', sa.Numeric(precision=24, scale=10), nullable=False),
    sa.Column('realised_pnl', sa.Numeric(precision=24, scale=10), nullable=False),
    sa.Column('unrealised_pnl', sa.Numeric(precision=24, scale=10), nullable=False),
    sa.Column('open_positions', sa.Integer(), nullable=False),
    sa.Column('details', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_portfolio_snapshots')),
    sa.UniqueConstraint('venue', 'timestamp', name='uq_portfolio_snapshots_venue')
    )
    op.create_index(op.f('ix_portfolio_snapshots_timestamp'), 'portfolio_snapshots', ['timestamp'], unique=False)
    op.create_index(op.f('ix_portfolio_snapshots_venue'), 'portfolio_snapshots', ['venue'], unique=False)
    op.create_table('risk_events',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('timestamp', sa.DateTime(timezone=True), nullable=False),
    sa.Column('venue', sa.String(length=24), nullable=False),
    sa.Column('symbol', sa.String(length=32), nullable=True),
    sa.Column('decision', sa.String(length=16), nullable=False),
    sa.Column('rule', sa.String(length=64), nullable=False),
    sa.Column('reason', sa.Text(), nullable=False),
    sa.Column('signal_id', sa.Integer(), nullable=True),
    sa.Column('details', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_risk_events'))
    )
    op.create_index(op.f('ix_risk_events_decision'), 'risk_events', ['decision'], unique=False)
    op.create_index(op.f('ix_risk_events_signal_id'), 'risk_events', ['signal_id'], unique=False)
    op.create_index(op.f('ix_risk_events_symbol'), 'risk_events', ['symbol'], unique=False)
    op.create_index(op.f('ix_risk_events_timestamp'), 'risk_events', ['timestamp'], unique=False)
    op.create_table('sentiment_scores',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('article_id', sa.Integer(), nullable=True),
    sa.Column('symbol', sa.String(length=32), nullable=True),
    sa.Column('computed_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('provider', sa.String(length=64), nullable=False),
    sa.Column('model', sa.String(length=128), nullable=True),
    sa.Column('sentiment', sa.Numeric(precision=6, scale=4), nullable=False),
    sa.Column('impact', sa.Numeric(precision=6, scale=4), nullable=True),
    sa.Column('importance', sa.Numeric(precision=6, scale=4), nullable=True),
    sa.Column('confidence', sa.Numeric(precision=6, scale=4), nullable=True),
    sa.Column('event_type', sa.String(length=64), nullable=True),
    sa.Column('duration_estimate', sa.String(length=32), nullable=True),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_sentiment_scores'))
    )
    op.create_index(op.f('ix_sentiment_scores_article_id'), 'sentiment_scores', ['article_id'], unique=False)
    op.create_index(op.f('ix_sentiment_scores_computed_at'), 'sentiment_scores', ['computed_at'], unique=False)
    op.create_index(op.f('ix_sentiment_scores_symbol'), 'sentiment_scores', ['symbol'], unique=False)
    op.create_index('ix_sentiment_scores_symbol_time', 'sentiment_scores', ['symbol', 'computed_at'], unique=False)
    op.create_table('signals',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('symbol', sa.String(length=32), nullable=False),
    sa.Column('timeframe', sa.String(length=8), nullable=False),
    sa.Column('open_time', sa.DateTime(timezone=True), nullable=False),
    sa.Column('generated_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('action', sa.String(length=16), nullable=False),
    sa.Column('score', sa.Numeric(precision=6, scale=4), nullable=False),
    sa.Column('confidence', sa.Numeric(precision=6, scale=4), nullable=False),
    sa.Column('reason_codes', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('strategy_version', sa.String(length=32), nullable=False),
    sa.Column('fusion_method', sa.String(length=32), nullable=False),
    sa.Column('reference_price', sa.Numeric(precision=24, scale=10), nullable=True),
    sa.Column('risk_decision', sa.String(length=16), nullable=True),
    sa.Column('risk_reason', sa.Text(), nullable=True),
    sa.Column('venue', sa.String(length=24), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_signals')),
    sa.UniqueConstraint('symbol', 'timeframe', 'open_time', 'strategy_version', 'venue', name='uq_signals_symbol')
    )
    op.create_index(op.f('ix_signals_action'), 'signals', ['action'], unique=False)
    op.create_index(op.f('ix_signals_generated_at'), 'signals', ['generated_at'], unique=False)
    op.create_index(op.f('ix_signals_risk_decision'), 'signals', ['risk_decision'], unique=False)
    op.create_index(op.f('ix_signals_strategy_version'), 'signals', ['strategy_version'], unique=False)
    op.create_index(op.f('ix_signals_symbol'), 'signals', ['symbol'], unique=False)
    op.create_table('system_events',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('timestamp', sa.DateTime(timezone=True), nullable=False),
    sa.Column('level', sa.String(length=16), nullable=False),
    sa.Column('component', sa.String(length=64), nullable=False),
    sa.Column('event_type', sa.String(length=64), nullable=False),
    sa.Column('message', sa.Text(), nullable=False),
    sa.Column('metadata', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_system_events'))
    )
    op.create_index('ix_system_events_component_ts', 'system_events', ['component', 'timestamp'], unique=False)
    op.create_index(op.f('ix_system_events_timestamp'), 'system_events', ['timestamp'], unique=False)
    op.create_table('system_settings',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('key', sa.String(length=128), nullable=False),
    sa.Column('value', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('editable', sa.Boolean(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_system_settings'))
    )
    op.create_index(op.f('ix_system_settings_key'), 'system_settings', ['key'], unique=True)
    op.create_table('technical_features',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('symbol', sa.String(length=32), nullable=False),
    sa.Column('timeframe', sa.String(length=8), nullable=False),
    sa.Column('open_time', sa.DateTime(timezone=True), nullable=False),
    sa.Column('feature_version', sa.String(length=32), nullable=False),
    sa.Column('features', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_technical_features')),
    sa.UniqueConstraint('symbol', 'timeframe', 'open_time', 'feature_version', name='uq_technical_features_symbol')
    )
    op.create_index(op.f('ix_technical_features_feature_version'), 'technical_features', ['feature_version'], unique=False)
    op.create_table('trades',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('venue', sa.String(length=24), nullable=False),
    sa.Column('symbol', sa.String(length=32), nullable=False),
    sa.Column('position_id', sa.Integer(), nullable=True),
    sa.Column('signal_id', sa.Integer(), nullable=True),
    sa.Column('side', sa.String(length=8), nullable=False),
    sa.Column('quantity', sa.Numeric(precision=28, scale=12), nullable=False),
    sa.Column('entry_price', sa.Numeric(precision=24, scale=10), nullable=False),
    sa.Column('exit_price', sa.Numeric(precision=24, scale=10), nullable=False),
    sa.Column('entry_time', sa.DateTime(timezone=True), nullable=False),
    sa.Column('exit_time', sa.DateTime(timezone=True), nullable=False),
    sa.Column('gross_pnl', sa.Numeric(precision=24, scale=10), nullable=False),
    sa.Column('fees', sa.Numeric(precision=24, scale=10), nullable=False),
    sa.Column('slippage_cost', sa.Numeric(precision=24, scale=10), nullable=False),
    sa.Column('net_pnl', sa.Numeric(precision=24, scale=10), nullable=False),
    sa.Column('return_pct', sa.Numeric(precision=18, scale=8), nullable=False),
    sa.Column('mae', sa.Numeric(precision=18, scale=8), nullable=True),
    sa.Column('mfe', sa.Numeric(precision=18, scale=8), nullable=True),
    sa.Column('exit_reason', sa.String(length=32), nullable=True),
    sa.Column('strategy_version', sa.String(length=32), nullable=True),
    sa.Column('model_version', sa.String(length=64), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_trades'))
    )
    op.create_index(op.f('ix_trades_exit_time'), 'trades', ['exit_time'], unique=False)
    op.create_index(op.f('ix_trades_model_version'), 'trades', ['model_version'], unique=False)
    op.create_index(op.f('ix_trades_position_id'), 'trades', ['position_id'], unique=False)
    op.create_index(op.f('ix_trades_signal_id'), 'trades', ['signal_id'], unique=False)
    op.create_index(op.f('ix_trades_strategy_version'), 'trades', ['strategy_version'], unique=False)
    op.create_index(op.f('ix_trades_symbol'), 'trades', ['symbol'], unique=False)
    op.create_index(op.f('ix_trades_venue'), 'trades', ['venue'], unique=False)
    op.create_index('ix_trades_venue_exit_time', 'trades', ['venue', 'exit_time'], unique=False)
    op.create_table('training_runs',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('job_id', sa.String(length=64), nullable=False),
    sa.Column('model_id', sa.String(length=64), nullable=False),
    sa.Column('model_type', sa.String(length=32), nullable=False),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('experiment_kind', sa.String(length=32), nullable=False),
    sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('data_range', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('parameters', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('results', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('resulting_model_version', sa.String(length=64), nullable=True),
    sa.Column('error', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_training_runs'))
    )
    op.create_index(op.f('ix_training_runs_job_id'), 'training_runs', ['job_id'], unique=True)
    op.create_index(op.f('ix_training_runs_model_id'), 'training_runs', ['model_id'], unique=False)
    op.create_index(op.f('ix_training_runs_status'), 'training_runs', ['status'], unique=False)
    op.create_table('backtest_trades',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('run_id', sa.Integer(), nullable=False),
    sa.Column('symbol', sa.String(length=32), nullable=False),
    sa.Column('side', sa.String(length=8), nullable=False),
    sa.Column('quantity', sa.Numeric(precision=28, scale=12), nullable=False),
    sa.Column('entry_time', sa.DateTime(timezone=True), nullable=False),
    sa.Column('entry_price', sa.Numeric(precision=24, scale=10), nullable=False),
    sa.Column('exit_time', sa.DateTime(timezone=True), nullable=False),
    sa.Column('exit_price', sa.Numeric(precision=24, scale=10), nullable=False),
    sa.Column('gross_pnl', sa.Numeric(precision=24, scale=10), nullable=False),
    sa.Column('fees', sa.Numeric(precision=24, scale=10), nullable=False),
    sa.Column('slippage_cost', sa.Numeric(precision=24, scale=10), nullable=False),
    sa.Column('net_pnl', sa.Numeric(precision=24, scale=10), nullable=False),
    sa.Column('return_pct', sa.Numeric(precision=18, scale=8), nullable=False),
    sa.Column('mae', sa.Numeric(precision=18, scale=8), nullable=True),
    sa.Column('mfe', sa.Numeric(precision=18, scale=8), nullable=True),
    sa.Column('exit_reason', sa.String(length=32), nullable=True),
    sa.Column('signal_snapshot', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.ForeignKeyConstraint(['run_id'], ['backtest_runs.id'], name=op.f('fk_backtest_trades_run_id_backtest_runs'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_backtest_trades'))
    )
    op.create_index(op.f('ix_backtest_trades_run_id'), 'backtest_trades', ['run_id'], unique=False)
    op.create_index('ix_backtest_trades_run_symbol', 'backtest_trades', ['run_id', 'symbol'], unique=False)
    op.create_table('signal_components',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('signal_id', sa.Integer(), nullable=False),
    sa.Column('kind', sa.String(length=32), nullable=False),
    sa.Column('score', sa.Numeric(precision=6, scale=4), nullable=False),
    sa.Column('weight', sa.Numeric(precision=6, scale=4), nullable=False),
    sa.Column('confidence', sa.Numeric(precision=6, scale=4), nullable=True),
    sa.Column('version', sa.String(length=64), nullable=True),
    sa.Column('active', sa.Boolean(), nullable=False),
    sa.Column('details', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.ForeignKeyConstraint(['signal_id'], ['signals.id'], name=op.f('fk_signal_components_signal_id_signals'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_signal_components')),
    sa.UniqueConstraint('signal_id', 'kind', name='uq_signal_components_signal_id')
    )
    op.create_index(op.f('ix_signal_components_signal_id'), 'signal_components', ['signal_id'], unique=False)


def downgrade() -> None:
    op.drop_table('signal_components')
    op.drop_table('backtest_trades')
    op.drop_table('training_runs')
    op.drop_table('trades')
    op.drop_table('technical_features')
    op.drop_table('system_settings')
    op.drop_table('system_events')
    op.drop_table('signals')
    op.drop_table('sentiment_scores')
    op.drop_table('risk_events')
    op.drop_table('portfolio_snapshots')
    op.drop_table('patterns')
    op.drop_table('pattern_statistics')
    op.drop_table('paper_positions')
    op.drop_table('paper_orders')
    op.drop_table('news_articles')
    op.drop_table('model_versions')
    op.drop_table('model_predictions')
    op.drop_table('model_metrics')
    op.drop_table('market_regimes')
    op.drop_table('market_data_metadata')
    op.drop_table('macro_events')
    op.drop_table('live_positions')
    op.drop_table('live_orders')
    op.drop_table('execution_events')
    op.drop_table('exchange_settings')
    op.drop_table('candles')
    op.drop_table('backtest_runs')
    op.drop_table('audit_logs')
    op.drop_table('assets')
