import asyncio
import pytest

from oasis.social_platform.channel import AsyncSafeDict, Channel

@pytest.mark.asyncio
async def test_async_safe_dict_put_get():
    safe_dict = AsyncSafeDict()
    await safe_dict.put("key1", "val1")
    val = await safe_dict.get("key1")
    assert val == "val1"

@pytest.mark.asyncio
async def test_async_safe_dict_pop():
    safe_dict = AsyncSafeDict()
    await safe_dict.put("key2", "val2")
    val = await safe_dict.pop("key2")
    assert val == "val2"
    val_after = await safe_dict.get("key2")
    assert val_after is None

@pytest.mark.asyncio
async def test_async_safe_dict_keys():
    safe_dict = AsyncSafeDict()
    await safe_dict.put("k1", "v1")
    await safe_dict.put("k2", "v2")
    keys = await safe_dict.keys()
    assert set(keys) == {"k1", "k2"}

@pytest.mark.asyncio
async def test_async_safe_dict_get_default():
    safe_dict = AsyncSafeDict()
    val = await safe_dict.get("not_exist", "default_val")
    assert val == "default_val"

@pytest.mark.asyncio
async def test_channel_send_and_read():
    chan = Channel()
    message = ("msg_id_123", "action_data")
    await chan.send_to(message)
    
    # Needs to run concurrently, read_from_send_queue blocks until msg is there
    # It loops if not. We'll use timeout to prevent infinite block just in case
    async def read_msg():
        return await chan.read_from_send_queue("msg_id_123")
        
    res = await asyncio.wait_for(read_msg(), timeout=1.0)
    assert res == message

@pytest.mark.asyncio
async def test_channel_receive_queue():
    chan = Channel()
    
    # write
    msg_id = await chan.write_to_receive_queue("test_action")
    
    # receive
    received = await chan.receive_from()
    assert received[0] == msg_id
    assert received[1] == "test_action"

@pytest.mark.asyncio
async def test_concurrent_put_get():
    safe_dict = AsyncSafeDict()
    async def worker(idx):
        await safe_dict.put(f"key_{idx}", idx)
        
    await asyncio.gather(*(worker(i) for i in range(10)))
    keys = await safe_dict.keys()
    assert len(keys) == 10

@pytest.mark.asyncio
async def test_multiple_messages_channel():
    chan = Channel()
    await chan.write_to_receive_queue("action 1")
    await chan.write_to_receive_queue("action 2")
    
    msg1 = await chan.receive_from()
    msg2 = await chan.receive_from()
    
    assert msg1[1] == "action 1"
    assert msg2[1] == "action 2"
