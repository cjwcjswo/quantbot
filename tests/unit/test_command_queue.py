"""Tests for the Redis-backed command queue."""

from packages.messaging import Command, CommandQueue, CommandType


async def test_publish_and_consume_roundtrip(redis):
    q = CommandQueue(redis)
    await q.publish(Command(type=CommandType.START_BOT))
    cmd = await q.consume(timeout=1.0)
    assert cmd is not None
    assert cmd.type == CommandType.START_BOT


async def test_consume_returns_none_on_timeout(redis):
    q = CommandQueue(redis)
    assert await q.consume(timeout=0.05) is None


async def test_fifo_order(redis):
    q = CommandQueue(redis)
    await q.publish(Command(type=CommandType.START_BOT))
    await q.publish(Command(type=CommandType.PAUSE_TRADING))
    first = await q.consume(timeout=1.0)
    second = await q.consume(timeout=1.0)
    assert first.type == CommandType.START_BOT
    assert second.type == CommandType.PAUSE_TRADING


async def test_payload_preserved(redis):
    q = CommandQueue(redis)
    await q.publish(
        Command(type=CommandType.CANCEL_ORDER, payload={"symbol": "BTCUSDT"})
    )
    cmd = await q.consume(timeout=1.0)
    assert cmd.payload == {"symbol": "BTCUSDT"}
