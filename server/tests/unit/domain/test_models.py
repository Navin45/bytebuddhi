from uuid import uuid4

from app.domain.models.conversation import Conversation
from app.domain.models.message import Message
from app.domain.models.project import Project
from app.domain.models.user import User


def test_user_create():
    user = User.create(
        email="test@example.com",
        username="testuser",
        password_hash="hashed_secret",
    )
    assert user.email == "test@example.com"
    assert user.username == "testuser"
    assert user.is_active is True


def test_project_create():
    user_id = uuid4()
    project = Project.create(
        user_id=user_id,
        name="Test Project",
        description="A project for testing",
    )
    assert project.user_id == user_id
    assert project.name == "Test Project"
    assert project.is_active is True


def test_conversation_and_message_create():
    user_id = uuid4()
    project_id = uuid4()
    conv = Conversation.create(
        user_id=user_id,
        project_id=project_id,
        title="My Conversation",
    )
    assert conv.user_id == user_id
    assert conv.project_id == project_id
    assert conv.title == "My Conversation"

    msg = Message.create(
        conversation_id=conv.id,
        role="user",
        content="Hello ByteBuddhi!",
    )
    assert msg.conversation_id == conv.id
    assert msg.role == "user"
    assert msg.content == "Hello ByteBuddhi!"
