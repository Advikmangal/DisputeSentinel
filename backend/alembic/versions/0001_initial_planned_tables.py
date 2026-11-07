"""initial planned tables

Revision ID: 0001
Revises: none
"""
from alembic import op
import sqlalchemy as sa


revision = '0001'
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('merchants',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('email', sa.String(length=320), nullable=False),
    sa.Column('password_hash', sa.Text(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_merchants')),
    sa.UniqueConstraint('email', name=op.f('uq_merchants_email'))
    )
    op.create_table('webhook_events',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('paypal_event_id', sa.String(length=127), nullable=False),
    sa.Column('event_type', sa.String(length=100), nullable=False),
    sa.Column('payload', sa.JSON(), nullable=False),
    sa.Column('processed_at', sa.DateTime(timezone=True), nullable=True),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_webhook_events')),
    sa.UniqueConstraint('paypal_event_id', name=op.f('uq_webhook_events_paypal_event_id'))
    )
    op.create_table('audit_log',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('merchant_id', sa.Integer(), nullable=False),
    sa.Column('action', sa.String(length=100), nullable=False),
    sa.Column('entity_type', sa.String(length=100), nullable=False),
    sa.Column('entity_id', sa.Integer(), nullable=False),
    sa.Column('detail', sa.JSON(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['merchant_id'], ['merchants.id'], name=op.f('fk_audit_log_merchant_id_merchants')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_audit_log'))
    )
    op.create_index(op.f('ix_audit_log_action'), 'audit_log', ['action'], unique=False)
    op.create_index(op.f('ix_audit_log_merchant_id'), 'audit_log', ['merchant_id'], unique=False)
    op.create_table('transactions',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('merchant_id', sa.Integer(), nullable=False),
    sa.Column('paypal_order_id', sa.String(length=127), nullable=False),
    sa.Column('paypal_capture_id', sa.String(length=127), nullable=True),
    sa.Column('amount', sa.Numeric(precision=18, scale=2), nullable=False),
    sa.Column('currency', sa.String(length=3), nullable=False),
    sa.Column('status', sa.String(length=20), server_default='CREATED', nullable=False),
    sa.Column('payer_email', sa.String(length=320), nullable=True),
    sa.Column('description', sa.Text(), server_default='', nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('captured_at', sa.DateTime(timezone=True), nullable=True),
    sa.CheckConstraint("status IN ('CREATED', 'VERIFIED')", name=op.f('ck_transactions_status')),
    sa.CheckConstraint('amount > 0', name=op.f('ck_transactions_positive_amount')),
    sa.ForeignKeyConstraint(['merchant_id'], ['merchants.id'], name=op.f('fk_transactions_merchant_id_merchants')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_transactions')),
    sa.UniqueConstraint('paypal_capture_id', name=op.f('uq_transactions_paypal_capture_id')),
    sa.UniqueConstraint('paypal_order_id', name=op.f('uq_transactions_paypal_order_id'))
    )
    op.create_index(op.f('ix_transactions_merchant_id'), 'transactions', ['merchant_id'], unique=False)
    op.create_table('disputes',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('transaction_id', sa.Integer(), nullable=True),
    sa.Column('paypal_dispute_id', sa.String(length=127), nullable=False),
    sa.Column('reason', sa.String(length=100), nullable=False),
    sa.Column('status', sa.String(length=100), nullable=False),
    sa.Column('amount', sa.Numeric(precision=18, scale=2), nullable=False),
    sa.Column('response_due_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('is_fixture', sa.Boolean(), server_default='false', nullable=False),
    sa.Column('raw', sa.JSON(), nullable=False),
    sa.ForeignKeyConstraint(['transaction_id'], ['transactions.id'], name=op.f('fk_disputes_transaction_id_transactions')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_disputes')),
    sa.UniqueConstraint('paypal_dispute_id', name=op.f('uq_disputes_paypal_dispute_id'))
    )
    op.create_index(op.f('ix_disputes_transaction_id'), 'disputes', ['transaction_id'], unique=False)
    op.create_table('evidence_documents',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('transaction_id', sa.Integer(), nullable=False),
    sa.Column('filename', sa.Text(), nullable=False),
    sa.Column('storage_path', sa.Text(), nullable=True),
    sa.Column('file_data', sa.LargeBinary(), nullable=False),
    sa.Column('mime_type', sa.String(length=100), nullable=False),
    sa.Column('size', sa.Integer(), nullable=False),
    sa.Column('text_content', sa.Text(), nullable=True),
    sa.Column('uploaded_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint('size >= 0 AND size <= 10000000', name=op.f('ck_evidence_documents_file_size')),
    sa.ForeignKeyConstraint(['transaction_id'], ['transactions.id'], name=op.f('fk_evidence_documents_transaction_id_transactions')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_evidence_documents'))
    )
    op.create_index(op.f('ix_evidence_documents_transaction_id'), 'evidence_documents', ['transaction_id'], unique=False)
    op.create_table('readiness_scores',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('transaction_id', sa.Integer(), nullable=False),
    sa.Column('score', sa.Integer(), nullable=False),
    sa.Column('breakdown', sa.JSON(), nullable=False),
    sa.Column('missing_items', sa.JSON(), nullable=False),
    sa.Column('computed_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint('score >= 0 AND score <= 100', name=op.f('ck_readiness_scores_score')),
    sa.ForeignKeyConstraint(['transaction_id'], ['transactions.id'], name=op.f('fk_readiness_scores_transaction_id_transactions')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_readiness_scores'))
    )
    op.create_index(op.f('ix_readiness_scores_transaction_id'), 'readiness_scores', ['transaction_id'], unique=False)
    op.create_table('dispute_responses',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('dispute_id', sa.Integer(), nullable=False),
    sa.Column('draft_text', sa.Text(), nullable=False),
    sa.Column('citations', sa.JSON(), nullable=False),
    sa.Column('status', sa.String(length=20), server_default='draft', nullable=False),
    sa.Column('approved_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('submitted_at', sa.DateTime(timezone=True), nullable=True),
    sa.CheckConstraint("status IN ('draft', 'approved', 'submitted', 'exported')", name=op.f('ck_dispute_responses_status')),
    sa.ForeignKeyConstraint(['dispute_id'], ['disputes.id'], name=op.f('fk_dispute_responses_dispute_id_disputes')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_dispute_responses'))
    )
    op.create_index(op.f('ix_dispute_responses_dispute_id'), 'dispute_responses', ['dispute_id'], unique=False)
    op.create_table('extracted_facts',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('document_id', sa.Integer(), nullable=False),
    sa.Column('fact_type', sa.String(length=100), nullable=False),
    sa.Column('value', sa.Text(), nullable=False),
    sa.Column('page', sa.Integer(), nullable=False),
    sa.Column('excerpt', sa.Text(), nullable=False),
    sa.Column('confidence', sa.Float(), nullable=False),
    sa.CheckConstraint('confidence >= 0 AND confidence <= 1', name=op.f('ck_extracted_facts_confidence')),
    sa.CheckConstraint('length(excerpt) > 0', name=op.f('ck_extracted_facts_excerpt')),
    sa.CheckConstraint('page > 0', name=op.f('ck_extracted_facts_page')),
    sa.ForeignKeyConstraint(['document_id'], ['evidence_documents.id'], name=op.f('fk_extracted_facts_document_id_evidence_documents')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_extracted_facts'))
    )
    op.create_index(op.f('ix_extracted_facts_document_id'), 'extracted_facts', ['document_id'], unique=False)


def downgrade():
    op.drop_index(op.f('ix_extracted_facts_document_id'), table_name='extracted_facts')
    op.drop_table('extracted_facts')
    op.drop_index(op.f('ix_dispute_responses_dispute_id'), table_name='dispute_responses')
    op.drop_table('dispute_responses')
    op.drop_index(op.f('ix_readiness_scores_transaction_id'), table_name='readiness_scores')
    op.drop_table('readiness_scores')
    op.drop_index(op.f('ix_evidence_documents_transaction_id'), table_name='evidence_documents')
    op.drop_table('evidence_documents')
    op.drop_index(op.f('ix_disputes_transaction_id'), table_name='disputes')
    op.drop_table('disputes')
    op.drop_index(op.f('ix_transactions_merchant_id'), table_name='transactions')
    op.drop_table('transactions')
    op.drop_index(op.f('ix_audit_log_merchant_id'), table_name='audit_log')
    op.drop_index(op.f('ix_audit_log_action'), table_name='audit_log')
    op.drop_table('audit_log')
    op.drop_table('webhook_events')
    op.drop_table('merchants')
