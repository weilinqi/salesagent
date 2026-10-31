"""Small helpers for handing a recorded voice turn to the realtime service."""

import asyncio
from collections.abc import Awaitable, Callable, Sequence


async def finish_voice_input(
    queue: asyncio.Queue,
    webm_chunks: Sequence[bytes],
    mime: str,
    convert: Callable[[bytes, str], Awaitable[bytes | None]],
) -> None:
    """Send the final decoded audio before the end-of-input marker."""
    try:
        if webm_chunks:
            pcm = await convert(b"".join(webm_chunks), mime)
            if pcm:
                await queue.put(pcm)
    finally:
        await queue.put(None)
