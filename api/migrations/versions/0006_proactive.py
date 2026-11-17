"""proactive notices and auto-detected incidents

Revision ID: 0006
Revises: 0005
"""
from alembic import op
import sqlalchemy as sa


revision = '0006'
down_revision = '0005'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column('incidents', 'created_by', existing_type=sa.String(length=32), nullable=True)
    op.add_column('incidents', sa.Column('source', sa.String(length=8), server_default='manual', nullable=False))
    op.alter_column('sim_replies', 'reply_to_message_id', existing_type=sa.Integer(), nullable=True)


def downgrade() -> None:
    op.execute("DELETE FROM sim_replies WHERE reply_to_message_id IS NULL")
    op.alter_column('sim_replies', 'reply_to_message_id', existing_type=sa.Integer(), nullable=False)
    op.drop_column('incidents', 'source')
    op.execute("DELETE FROM incidents WHERE created_by IS NULL")
    op.alter_column('incidents', 'created_by', existing_type=sa.String(length=32), nullable=False)
