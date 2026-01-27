"""add_agent_checkpoints_table

Revision ID: 36144d2c114a
Revises: 94ae091b2313
Create Date: 2026-01-27 23:38:30.223523

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '36144d2c114a'
down_revision: Union[str, Sequence[str], None] = '94ae091b2313'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Create agent_checkpoints table
    op.create_table(
        'agent_checkpoints',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('thread_id', sa.String(length=255), nullable=False),
        sa.Column('checkpoint_id', sa.String(length=255), nullable=False),
        sa.Column('parent_checkpoint_id', sa.String(length=255), nullable=True),
        sa.Column('checkpoint_data', sa.Text(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id')
    )
    
    # Create indexes
    op.create_index('ix_agent_checkpoints_thread_id', 'agent_checkpoints', ['thread_id'], unique=False)
    op.create_index('ix_agent_checkpoints_checkpoint_id', 'agent_checkpoints', ['checkpoint_id'], unique=True)



def downgrade() -> None:
    """Downgrade schema."""
    # Drop indexes
    op.drop_index('ix_agent_checkpoints_checkpoint_id', table_name='agent_checkpoints')
    op.drop_index('ix_agent_checkpoints_thread_id', table_name='agent_checkpoints')
    
    # Drop table
    op.drop_table('agent_checkpoints')

