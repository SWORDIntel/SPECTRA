import pytest
from unittest.mock import AsyncMock, MagicMock
from tgarchive.osint.intelligence import IntelligenceCollector

@pytest.fixture
def mock_config():
    return MagicMock()

@pytest.fixture
def mock_db():
    db = MagicMock()
    db.connect = AsyncMock()
    return db

@pytest.fixture
def mock_client():
    client = AsyncMock()
    return client

@pytest.mark.asyncio
async def test_add_target(mock_config, mock_db, mock_client):
    # Arrange
    collector = IntelligenceCollector(mock_config, mock_db, mock_client)

    mock_user = MagicMock()
    mock_user.id = 123
    mock_user.username = "testuser"
    mock_user.first_name = "Test"
    mock_user.last_name = "User"
    mock_client.get_entity.return_value = mock_user

    # Act
    await collector.add_target("testuser", "notes")

    # Assert
    mock_client.get_entity.assert_called_with("testuser")

    # Check that the user was inserted into the 'users' table
    mock_db.connect.return_value.__aenter__.return_value.execute.assert_any_call(
        "\n                    INSERT OR IGNORE INTO users (id, username, first_name, last_name, last_updated)\n                    VALUES (?, ?, ?, ?, datetime('now'))\n                    ",
        (123, "testuser", "Test", "User")
    )

    # Check that the user was inserted into the 'osint_targets' table
    mock_db.connect.return_value.__aenter__.return_value.execute.assert_any_call(
        "\n                    INSERT OR REPLACE INTO osint_targets (user_id, username, notes, created_at)\n                    VALUES (?, ?, ?, datetime('now'))\n                    ",
        (123, "testuser", "notes")
    )

    # Check that the transaction was committed
    mock_db.connect.return_value.__aenter__.return_value.commit.assert_called_once()

@pytest.mark.asyncio
async def test_remove_target(mock_config, mock_db, mock_client):
    # Arrange
    collector = IntelligenceCollector(mock_config, mock_db, mock_client)
    mock_db.connect.return_value.__aenter__.return_value.execute.return_value.fetchone.return_value = (123,)

    # Act
    await collector.remove_target("testuser")

    # Assert
    mock_db.connect.return_value.__aenter__.return_value.execute.assert_any_call(
        "SELECT user_id FROM osint_targets WHERE username = ?", ("testuser",)
    )
    mock_db.connect.return_value.__aenter__.return_value.execute.assert_any_call(
        "DELETE FROM osint_targets WHERE user_id = ?", (123,)
    )
    mock_db.connect.return_value.__aenter__.return_value.commit.assert_called_once()

@pytest.mark.asyncio
async def test_list_targets(mock_config, mock_db, mock_client):
    # Arrange
    collector = IntelligenceCollector(mock_config, mock_db, mock_client)
    mock_db.connect.return_value.__aenter__.return_value.execute.return_value.fetchall.return_value = [
        (123, "testuser1", "notes1", "2023-01-01"),
        (456, "testuser2", "notes2", "2023-01-02"),
    ]

    # Act
    targets = await collector.list_targets()

    # Assert
    assert len(targets) == 2
    assert targets[0]["username"] == "testuser1"
    assert targets[1]["user_id"] == 456

@pytest.mark.asyncio
async def test_scan_channel(mock_config, mock_db, mock_client):
    # Arrange
    collector = IntelligenceCollector(mock_config, mock_db, mock_client)

    # Mock the database to return the target user
    mock_db.connect.return_value.__aenter__.return_value.execute.return_value.fetchone.return_value = (123,)

    # Mock the client to return messages
    mock_channel_entity = MagicMock()
    mock_channel_entity.id = 789
    mock_client.get_entity.return_value = mock_channel_entity

    mock_message1 = MagicMock()
    mock_message1.sender_id = 123
    mock_message1.reply_to_msg_id = 100

    mock_replied_to_msg = MagicMock()
    mock_replied_to_msg.sender_id = 456

    async def mock_iter_messages(*args, **kwargs):
        yield mock_message1

    mock_client.iter_messages.return_value = mock_iter_messages()
    mock_client.get_messages.return_value = mock_replied_to_msg

    # Act
    await collector.scan_channel(789, "testuser")

    # Assert
    # Check that an interaction was logged
    mock_db.connect.return_value.__aenter__.return_value.execute.assert_any_call(
        "\n                    INSERT INTO osint_interactions (source_user_id, target_user_id, interaction_type, channel_id, message_id, timestamp)\n                    VALUES (?, ?, ?, ?, ?, datetime('now'))\n                    ",
        (123, 456, "reply_to", 789, mock_message1.id)
    )

@pytest.mark.asyncio
async def test_get_network(mock_config, mock_db, mock_client):
    # Arrange
    collector = IntelligenceCollector(mock_config, mock_db, mock_client)
    mock_db.connect.return_value.__aenter__.return_value.execute.return_value.fetchone.return_value = (123,)
    mock_db.connect.return_value.__aenter__.return_value.execute.return_value.fetchall.return_value = [
        (123, 456, "reply_to", 789, 100, "2023-01-01"),
    ]

    # Act
    network = await collector.get_network("testuser")

    # Assert
    assert len(network) == 1
    assert network[0]["source_user_id"] == 123
