from app.bot.state_storage import message_state_key, user_state_key
from app.bot.utils import is_private_chat


def test_state_key_is_scoped_to_chat_and_user():
    assert user_state_key(100, 1) != user_state_key(100, 2)
    assert user_state_key(100, 1) != user_state_key(101, 1)


def test_state_key_has_no_pair_collisions_for_small_ids():
    keys = {
        user_state_key(peer_id, user_id)
        for peer_id in range(-2, 4)
        for user_id in range(-2, 4)
    }

    assert len(keys) == 36


def test_private_messages_keep_existing_state_key():
    assert message_state_key(42, 42) == 42


def test_group_messages_get_distinct_state_keys_per_user():
    assert message_state_key(2_000_000_042, 42) != message_state_key(2_000_000_042, 43)


def test_private_chat_detection_uses_vk_peer_and_sender_ids():
    assert is_private_chat(42, 42)
    assert not is_private_chat(2_000_000_042, 42)