"""add_rls_policies

Revision ID: 4dad8f1bf999
Revises: 36144d2c114a
Create Date: 2026-01-27 23:42:54.809710

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '4dad8f1bf999'
down_revision: Union[str, Sequence[str], None] = '36144d2c114a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Enable RLS and create policies for all tables."""
    
    # Enable RLS on all tables
    op.execute("ALTER TABLE users ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE projects ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE files ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE code_chunks ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE code_embeddings ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE conversations ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE messages ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE agent_checkpoints ENABLE ROW LEVEL SECURITY")
    
    # Users table policies
    op.execute('''
        CREATE POLICY "Users can view own profile"
        ON users FOR SELECT
        USING (auth.uid()::uuid = id)
    ''')
    
    op.execute('''
        CREATE POLICY "Users can update own profile"
        ON users FOR UPDATE
        USING (auth.uid()::uuid = id)
    ''')
    
    op.execute('''
        CREATE POLICY "Allow user registration"
        ON users FOR INSERT
        WITH CHECK (true)
    ''')
    
    # Projects table policies
    op.execute('''
        CREATE POLICY "Users can view own projects"
        ON projects FOR SELECT
        USING (auth.uid()::uuid = user_id)
    ''')
    
    op.execute('''
        CREATE POLICY "Users can create own projects"
        ON projects FOR INSERT
        WITH CHECK (auth.uid()::uuid = user_id)
    ''')
    
    op.execute('''
        CREATE POLICY "Users can update own projects"
        ON projects FOR UPDATE
        USING (auth.uid()::uuid = user_id)
    ''')
    
    op.execute('''
        CREATE POLICY "Users can delete own projects"
        ON projects FOR DELETE
        USING (auth.uid()::uuid = user_id)
    ''')
    
    # Files table policies
    op.execute('''
        CREATE POLICY "Users can view own project files"
        ON files FOR SELECT
        USING (
            EXISTS (
                SELECT 1 FROM projects
                WHERE projects.id = files.project_id
                AND projects.user_id = auth.uid()::uuid
            )
        )
    ''')
    
    op.execute('''
        CREATE POLICY "Users can create files in own projects"
        ON files FOR INSERT
        WITH CHECK (
            EXISTS (
                SELECT 1 FROM projects
                WHERE projects.id = files.project_id
                AND projects.user_id = auth.uid()::uuid
            )
        )
    ''')
    
    op.execute('''
        CREATE POLICY "Users can update own project files"
        ON files FOR UPDATE
        USING (
            EXISTS (
                SELECT 1 FROM projects
                WHERE projects.id = files.project_id
                AND projects.user_id = auth.uid()::uuid
            )
        )
    ''')
    
    op.execute('''
        CREATE POLICY "Users can delete own project files"
        ON files FOR DELETE
        USING (
            EXISTS (
                SELECT 1 FROM projects
                WHERE projects.id = files.project_id
                AND projects.user_id = auth.uid()::uuid
            )
        )
    ''')
    
    # Code chunks table policies
    op.execute('''
        CREATE POLICY "Users can view own project code chunks"
        ON code_chunks FOR SELECT
        USING (
            EXISTS (
                SELECT 1 FROM projects
                WHERE projects.id = code_chunks.project_id
                AND projects.user_id = auth.uid()::uuid
            )
        )
    ''')
    
    op.execute('''
        CREATE POLICY "Users can create code chunks in own projects"
        ON code_chunks FOR INSERT
        WITH CHECK (
            EXISTS (
                SELECT 1 FROM projects
                WHERE projects.id = code_chunks.project_id
                AND projects.user_id = auth.uid()::uuid
            )
        )
    ''')
    
    op.execute('''
        CREATE POLICY "Users can update own project code chunks"
        ON code_chunks FOR UPDATE
        USING (
            EXISTS (
                SELECT 1 FROM projects
                WHERE projects.id = code_chunks.project_id
                AND projects.user_id = auth.uid()::uuid
            )
        )
    ''')
    
    op.execute('''
        CREATE POLICY "Users can delete own project code chunks"
        ON code_chunks FOR DELETE
        USING (
            EXISTS (
                SELECT 1 FROM projects
                WHERE projects.id = code_chunks.project_id
                AND projects.user_id = auth.uid()::uuid
            )
        )
    ''')
    
    # Code embeddings table policies
    op.execute('''
        CREATE POLICY "Users can view own project embeddings"
        ON code_embeddings FOR SELECT
        USING (
            EXISTS (
                SELECT 1 FROM projects
                WHERE projects.id = code_embeddings.project_id
                AND projects.user_id = auth.uid()::uuid
            )
        )
    ''')
    
    op.execute('''
        CREATE POLICY "Users can create embeddings in own projects"
        ON code_embeddings FOR INSERT
        WITH CHECK (
            EXISTS (
                SELECT 1 FROM projects
                WHERE projects.id = code_embeddings.project_id
                AND projects.user_id = auth.uid()::uuid
            )
        )
    ''')
    
    op.execute('''
        CREATE POLICY "Users can delete own project embeddings"
        ON code_embeddings FOR DELETE
        USING (
            EXISTS (
                SELECT 1 FROM projects
                WHERE projects.id = code_embeddings.project_id
                AND projects.user_id = auth.uid()::uuid
            )
        )
    ''')
    
    # Conversations table policies
    op.execute('''
        CREATE POLICY "Users can view own conversations"
        ON conversations FOR SELECT
        USING (auth.uid()::uuid = user_id)
    ''')
    
    op.execute('''
        CREATE POLICY "Users can create own conversations"
        ON conversations FOR INSERT
        WITH CHECK (auth.uid()::uuid = user_id)
    ''')
    
    op.execute('''
        CREATE POLICY "Users can update own conversations"
        ON conversations FOR UPDATE
        USING (auth.uid()::uuid = user_id)
    ''')
    
    op.execute('''
        CREATE POLICY "Users can delete own conversations"
        ON conversations FOR DELETE
        USING (auth.uid()::uuid = user_id)
    ''')
    
    # Messages table policies
    op.execute('''
        CREATE POLICY "Users can view own conversation messages"
        ON messages FOR SELECT
        USING (
            EXISTS (
                SELECT 1 FROM conversations
                WHERE conversations.id = messages.conversation_id
                AND conversations.user_id = auth.uid()::uuid
            )
        )
    ''')
    
    op.execute('''
        CREATE POLICY "Users can create messages in own conversations"
        ON messages FOR INSERT
        WITH CHECK (
            EXISTS (
                SELECT 1 FROM conversations
                WHERE conversations.id = messages.conversation_id
                AND conversations.user_id = auth.uid()::uuid
            )
        )
    ''')
    
    op.execute('''
        CREATE POLICY "Users can update own conversation messages"
        ON messages FOR UPDATE
        USING (
            EXISTS (
                SELECT 1 FROM conversations
                WHERE conversations.id = messages.conversation_id
                AND conversations.user_id = auth.uid()::uuid
            )
        )
    ''')
    
    op.execute('''
        CREATE POLICY "Users can delete own conversation messages"
        ON messages FOR DELETE
        USING (
            EXISTS (
                SELECT 1 FROM conversations
                WHERE conversations.id = messages.conversation_id
                AND conversations.user_id = auth.uid()::uuid
            )
        )
    ''')
    
    # Agent checkpoints table policies
    op.execute('''
        CREATE POLICY "Users can view agent checkpoints"
        ON agent_checkpoints FOR SELECT
        USING (auth.uid() IS NOT NULL)
    ''')
    
    op.execute('''
        CREATE POLICY "Users can create agent checkpoints"
        ON agent_checkpoints FOR INSERT
        WITH CHECK (auth.uid() IS NOT NULL)
    ''')
    
    op.execute('''
        CREATE POLICY "Users can delete agent checkpoints"
        ON agent_checkpoints FOR DELETE
        USING (auth.uid() IS NOT NULL)
    ''')


def downgrade() -> None:
    """Disable RLS and drop all policies."""
    
    # Drop all policies (in reverse order)
    # Agent checkpoints
    op.execute('DROP POLICY IF EXISTS "Users can delete agent checkpoints" ON agent_checkpoints')
    op.execute('DROP POLICY IF EXISTS "Users can create agent checkpoints" ON agent_checkpoints')
    op.execute('DROP POLICY IF EXISTS "Users can view agent checkpoints" ON agent_checkpoints')
    
    # Messages
    op.execute('DROP POLICY IF EXISTS "Users can delete own conversation messages" ON messages')
    op.execute('DROP POLICY IF EXISTS "Users can update own conversation messages" ON messages')
    op.execute('DROP POLICY IF EXISTS "Users can create messages in own conversations" ON messages')
    op.execute('DROP POLICY IF EXISTS "Users can view own conversation messages" ON messages')
    
    # Conversations
    op.execute('DROP POLICY IF EXISTS "Users can delete own conversations" ON conversations')
    op.execute('DROP POLICY IF EXISTS "Users can update own conversations" ON conversations')
    op.execute('DROP POLICY IF EXISTS "Users can create own conversations" ON conversations')
    op.execute('DROP POLICY IF EXISTS "Users can view own conversations" ON conversations')
    
    # Code embeddings
    op.execute('DROP POLICY IF EXISTS "Users can delete own project embeddings" ON code_embeddings')
    op.execute('DROP POLICY IF EXISTS "Users can create embeddings in own projects" ON code_embeddings')
    op.execute('DROP POLICY IF EXISTS "Users can view own project embeddings" ON code_embeddings')
    
    # Code chunks
    op.execute('DROP POLICY IF EXISTS "Users can delete own project code chunks" ON code_chunks')
    op.execute('DROP POLICY IF EXISTS "Users can update own project code chunks" ON code_chunks')
    op.execute('DROP POLICY IF EXISTS "Users can create code chunks in own projects" ON code_chunks')
    op.execute('DROP POLICY IF EXISTS "Users can view own project code chunks" ON code_chunks')
    
    # Files
    op.execute('DROP POLICY IF EXISTS "Users can delete own project files" ON files')
    op.execute('DROP POLICY IF EXISTS "Users can update own project files" ON files')
    op.execute('DROP POLICY IF EXISTS "Users can create files in own projects" ON files')
    op.execute('DROP POLICY IF EXISTS "Users can view own project files" ON files')
    
    # Projects
    op.execute('DROP POLICY IF EXISTS "Users can delete own projects" ON projects')
    op.execute('DROP POLICY IF EXISTS "Users can update own projects" ON projects')
    op.execute('DROP POLICY IF EXISTS "Users can create own projects" ON projects')
    op.execute('DROP POLICY IF EXISTS "Users can view own projects" ON projects')
    
    # Users
    op.execute('DROP POLICY IF EXISTS "Allow user registration" ON users')
    op.execute('DROP POLICY IF EXISTS "Users can update own profile" ON users')
    op.execute('DROP POLICY IF EXISTS "Users can view own profile" ON users')
    
    # Disable RLS on all tables
    op.execute("ALTER TABLE agent_checkpoints DISABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE messages DISABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE conversations DISABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE code_embeddings DISABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE code_chunks DISABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE files DISABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE projects DISABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE users DISABLE ROW LEVEL SECURITY")
