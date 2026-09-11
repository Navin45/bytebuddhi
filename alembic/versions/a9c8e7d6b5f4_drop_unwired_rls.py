"""Drop unwired auth.uid() RLS and merge alembic heads.

Revision ID: a9c8e7d6b5f4
Revises: 4dad8f1bf999, 7a8e102b345c
Create Date: 2026-09-11 16:30:00.000000

ByteBuddhi authenticates with application JWTs, not PostgreSQL auth.uid().
The previous RLS policies were never connected to request identity, so they
looked like isolation without enforcing it. Application authorization is the
authoritative boundary. This migration removes the unused policies.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "a9c8e7d6b5f4"
down_revision: tuple[str, str] | Sequence[str] | None = ("4dad8f1bf999", "7a8e102b345c")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute('DROP POLICY IF EXISTS "Users can delete agent checkpoints" ON agent_checkpoints')
    op.execute('DROP POLICY IF EXISTS "Users can create agent checkpoints" ON agent_checkpoints')
    op.execute('DROP POLICY IF EXISTS "Users can view agent checkpoints" ON agent_checkpoints')

    op.execute('DROP POLICY IF EXISTS "Users can delete own conversation messages" ON messages')
    op.execute('DROP POLICY IF EXISTS "Users can update own conversation messages" ON messages')
    op.execute('DROP POLICY IF EXISTS "Users can create messages in own conversations" ON messages')
    op.execute('DROP POLICY IF EXISTS "Users can view own conversation messages" ON messages')

    op.execute('DROP POLICY IF EXISTS "Users can delete own conversations" ON conversations')
    op.execute('DROP POLICY IF EXISTS "Users can update own conversations" ON conversations')
    op.execute('DROP POLICY IF EXISTS "Users can create own conversations" ON conversations')
    op.execute('DROP POLICY IF EXISTS "Users can view own conversations" ON conversations')

    op.execute('DROP POLICY IF EXISTS "Users can delete own project embeddings" ON code_embeddings')
    op.execute('DROP POLICY IF EXISTS "Users can create embeddings in own projects" ON code_embeddings')
    op.execute('DROP POLICY IF EXISTS "Users can view own project embeddings" ON code_embeddings')

    op.execute('DROP POLICY IF EXISTS "Users can delete own project code chunks" ON code_chunks')
    op.execute('DROP POLICY IF EXISTS "Users can update own project code chunks" ON code_chunks')
    op.execute('DROP POLICY IF EXISTS "Users can create code chunks in own projects" ON code_chunks')
    op.execute('DROP POLICY IF EXISTS "Users can view own project code chunks" ON code_chunks')

    op.execute('DROP POLICY IF EXISTS "Users can delete own project files" ON files')
    op.execute('DROP POLICY IF EXISTS "Users can update own project files" ON files')
    op.execute('DROP POLICY IF EXISTS "Users can create files in own projects" ON files')
    op.execute('DROP POLICY IF EXISTS "Users can view own project files" ON files')

    op.execute('DROP POLICY IF EXISTS "Users can delete own projects" ON projects')
    op.execute('DROP POLICY IF EXISTS "Users can update own projects" ON projects')
    op.execute('DROP POLICY IF EXISTS "Users can create own projects" ON projects')
    op.execute('DROP POLICY IF EXISTS "Users can view own projects" ON projects')

    op.execute('DROP POLICY IF EXISTS "Allow user registration" ON users')
    op.execute('DROP POLICY IF EXISTS "Users can update own profile" ON users')
    op.execute('DROP POLICY IF EXISTS "Users can view own profile" ON users')

    op.execute("ALTER TABLE agent_checkpoints DISABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE messages DISABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE conversations DISABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE code_embeddings DISABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE code_chunks DISABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE files DISABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE projects DISABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE users DISABLE ROW LEVEL SECURITY")


def downgrade() -> None:
    """RLS is not restored. Application authorization remains the isolation boundary."""
    return
