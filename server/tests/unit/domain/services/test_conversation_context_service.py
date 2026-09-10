from uuid import uuid4

from app.domain.models.message import Message
from app.domain.services.conversation_context_service import ConversationContextService


def test_select_messages_for_context():
    conv_id = uuid4()
    messages = [Message.create(conversation_id=conv_id, role="user", content=f"Message {i}") for i in range(10)]

    selected = ConversationContextService.select_messages_for_context(
        messages, max_tokens=600, avg_tokens_per_message=200
    )
    assert len(selected) == 3
    assert selected[-1].content == "Message 9"


def test_should_summarize_conversation():
    assert ConversationContextService.should_summarize_conversation(20, threshold=20) is True
    assert ConversationContextService.should_summarize_conversation(19, threshold=20) is False


def test_estimate_token_count():
    assert ConversationContextService.estimate_token_count("12345678") == 2


def test_format_messages_for_llm():
    conv_id = uuid4()
    msgs = [
        Message.create(conversation_id=conv_id, role="user", content="hello"),
        Message.create(conversation_id=conv_id, role="assistant", content="world"),
    ]
    formatted = ConversationContextService.format_messages_for_llm(msgs)
    assert formatted == [
        {"role": "user", "content": "hello"},
        {"role": "assistant", "content": "world"},
    ]
