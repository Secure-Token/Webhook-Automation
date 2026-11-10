"""Webhook destination validation (SSRF protection).

Rules
- Only http/https with a hostname; no credentials in the URL.
- Production: https only, and every resolved IP must be public.
- Development: hosts listed in DEV_ALLOWED_HOSTS (localhost, ...) may use http, but only when
  ALLOW_LOCALHOST_WEBHOOKS=true. Anything else still has to be https + public.
- Validation is repeated at delivery time on freshly resolved addresses (DNS rebinding
  mitigation); the delivery client never follows redirects.
"""
import ipaddress
import socket
from urllib.parse import urlparse

from app.config import Settings, get_settings


class EndpointValidationError(ValueError):
    pass


def _is_public(ip: ipaddress._BaseAddress) -> bool:
    return not (ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast
                or ip.is_reserved or ip.is_unspecified)


def resolve_ips(host: str) -> list[ipaddress._BaseAddress]:
    try:
        return [ipaddress.ip_address(host)]
    except ValueError:
        pass
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror as exc:
        raise EndpointValidationError(f"Cannot resolve host '{host}'") from exc
    return list({ipaddress.ip_address(i[4][0]) for i in infos})


def validate_endpoint_url(url: str, settings: Settings | None = None, resolve: bool = True) -> str:
    settings = settings or get_settings()
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise EndpointValidationError("Endpoint URL must use http or https")
    if not parsed.hostname:
        raise EndpointValidationError("Endpoint URL must include a hostname")
    if parsed.username or parsed.password:
        raise EndpointValidationError("Credentials in the endpoint URL are not allowed")
    host = parsed.hostname.lower()

    dev_hosts = {h.strip().lower() for h in settings.dev_allowed_hosts.split(",") if h.strip()}
    dev_exception = (not settings.is_production) and settings.allow_localhost_webhooks and host in dev_hosts
    if dev_exception:
        return url

    if parsed.scheme != "https":
        raise EndpointValidationError("Endpoint URL must use https")
    if resolve:
        for ip in resolve_ips(host):
            if not _is_public(ip):
                raise EndpointValidationError("Endpoint resolves to a prohibited (non-public) address")
    else:
        try:
            literal = ipaddress.ip_address(host)
        except ValueError:
            literal = None
        if literal is not None and not _is_public(literal):
            raise EndpointValidationError("Endpoint is a prohibited (non-public) address")
        if literal is None and (host == "localhost" or host.endswith((".local", ".internal"))):
            raise EndpointValidationError("Endpoint host is prohibited")
    return url
