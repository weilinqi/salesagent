"""Bounded credential failover; never expose provider error bodies or credentials."""
import asyncio
from functools import wraps
import logging

logger = logging.getLogger(__name__)
ACCOUNT_CODES = {1002, 1004, 1008, 1041, 1045, 2045, 2046, 2047, 2049, 2053, 2056, 2062, 2067}
ACCOUNT_LABELS = {'authentication_error', 'invalid_api_key', 'rate_limit_error',
                  'rate_limit_exceeded', 'insufficient_quota', 'insufficient_balance_error'}


class MiniMaxAPIError(RuntimeError):
    def __init__(self, code=None, http_status=None):
        self.code = code
        self.http_status = http_status
        self.backup_attempted = False
        # Do not echo arbitrary server-provided strings (which may contain secrets).
        display = code if isinstance(code, int) or code in ACCOUNT_LABELS else 'unknown'
        super().__init__(f'MiniMax API error (code={display}, HTTP={http_status or "n/a"})')


def raise_api_error(payload):
    if not isinstance(payload, dict):
        return
    base = payload.get('base_resp') or {}
    code = base.get('status_code') if isinstance(base, dict) else None
    if code not in (None, 0, '0'):
        raise MiniMaxAPIError(_normalize_code(code))
    error = payload.get('error')
    if error:
        code = (error.get('code') or error.get('type')) if isinstance(error, dict) else None
        raise MiniMaxAPIError(_normalize_code(code))


def _normalize_code(code):
    if isinstance(code, int): return code
    if isinstance(code, str):
        if code.isdecimal(): return int(code)
        if code in ACCOUNT_LABELS: return code
    return None


async def check_http_response(response):
    if response.is_error:
        await response.aread()
        try:
            payload = response.json()
        except ValueError:
            payload = None
        # A specific business error takes priority over HTTP status. In particular,
        # never switch credentials for a content-policy or invalid-input error.
        raise_api_error(payload)
        raise MiniMaxAPIError(http_status=response.status_code)
    if 'application/json' in response.headers.get('content-type', ''):
        await response.aread()
        raise_api_error(response.json())


def credential_error(exc):
    if isinstance(exc, MiniMaxAPIError):
        if exc.code is not None:
            return exc.code in ACCOUNT_CODES or exc.code in ACCOUNT_LABELS
        return exc.http_status in (401, 402, 429)
    # WebSocket HTTP upgrade failures occur before any audio is sent.
    from websockets.exceptions import InvalidStatus
    if isinstance(exc, InvalidStatus):
        return exc.response.status_code in (401, 402, 429)
    return False


def backup_for(service, error):
    if not credential_error(error): return None
    backup = service._fallback_service()
    if backup is not None:
        logger.warning('MiniMax primary credential unavailable; trying configured backup once.')
    return backup


def key_fallback(method):
    @wraps(method)
    async def wrapped(self, *args, **kwargs):
        try:
            return await method(self, *args, **kwargs)
        except Exception as exc:
            backup = backup_for(self, exc)
            if backup is None: raise
        try:
            return await method(backup, *args, **kwargs)
        except MiniMaxAPIError as exc:
            exc.backup_attempted = True
            raise
    return wrapped


def stream_key_fallback(method):
    @wraps(method)
    async def wrapped(self, *args, **kwargs):
        emitted = False
        stream = method(self, *args, **kwargs)
        try:
            async for part in stream:
                emitted = True
                yield part
            return
        except Exception as exc:
            if emitted: raise
            backup = backup_for(self, exc)
            if backup is None: raise
        finally:
            await stream.aclose()
        stream = method(backup, *args, **kwargs)
        try:
            async for part in stream: yield part
        except MiniMaxAPIError as exc:
            exc.backup_attempted = True
            raise
        finally:
            await stream.aclose()
    return wrapped


class ReplayableAudio:
    """Replay at most 4 MiB of input, keeping source reads alive across attempt cancellation."""
    def __init__(self, source, limit=4 * 1024 * 1024):
        self.source = source.__aiter__()
        self.buffer = []
        self.limit = limit
        self.size = 0
        self.can_replay = True
        self.finished = False
        self.pending = None

    async def iterate(self):
        for chunk in self.buffer:
            yield chunk
        while not self.finished:
            if self.pending is None:
                self.pending = asyncio.ensure_future(self.source.__anext__())
            try:
                chunk = await asyncio.shield(self.pending)
            except StopAsyncIteration:
                self.finished = True
                self.pending = None
                break
            self.pending = None
            self.size += len(chunk) if chunk else 0
            if self.can_replay and self.size <= self.limit:
                self.buffer.append(chunk)
            else:
                self.can_replay = False
                self.buffer.clear()
            yield chunk

    async def close(self):
        if self.pending is not None:
            self.pending.cancel()
            try: await self.pending
            except (asyncio.CancelledError, StopAsyncIteration): pass
            self.pending = None
        if hasattr(self.source, 'aclose'):
            await self.source.aclose()
        self.buffer.clear()
