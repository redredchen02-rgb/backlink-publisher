"""SSL context helper with environment-gated insecure verification."""

from __future__ import annotations

import logging
import os
import ssl

_log = logging.getLogger(__name__)


def get_ssl_context() -> ssl.SSLContext:
    if os.environ.get("BACKLINK_PUBLISHER_ALLOW_INSECURE_SSL") == "1":
        if os.environ.get("FLASK_ENV") != "development":
            _log.warning(
                "BACKLINK_PUBLISHER_ALLOW_INSECURE_SSL=1 disables SSL "
                "verification for ALL outbound connections. This is a "
                "security risk in production. Unset it unless you "
                "specifically need insecure connections."
            )
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        return ctx
    return ssl.create_default_context()