import socket

import pytest


def test_default_suite_blocks_remote_sockets() -> None:
    with socket.socket() as client:
        with pytest.raises(RuntimeError, match="external network access is disabled"):
            client.connect(("203.0.113.1", 443))
