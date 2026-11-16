"""Exact origins in production; equivalent loopback spellings during local development."""
from urllib.parse import urlsplit


def allowed_websocket_origin(origin: str, configured: list[str], environment: str) -> bool:
    if origin in configured:
        return True
    if environment != 'development':
        return False

    def local_origin(value):
        try:
            parsed = urlsplit(value)
            if (parsed.scheme not in ('http', 'https')
                    or parsed.hostname not in ('localhost', '127.0.0.1', '::1')
                    or parsed.username or parsed.password or parsed.path or parsed.query or parsed.fragment):
                return None
            port = parsed.port if parsed.port is not None else (443 if parsed.scheme == 'https' else 80)
            return parsed.scheme, port
        except (ValueError, TypeError):
            return None

    candidate = local_origin(origin)
    return candidate is not None and any(local_origin(value) == candidate for value in configured)
