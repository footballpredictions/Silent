"""Public HTTP bootstrap/status server with a bounded wait for request headers.

Uvicorn's keep-alive timeout starts after a response. A TCP peer that never
finishes its first request can otherwise keep an accepted socket indefinitely.
The deadline ends at complete headers, preserving slow bodies and API responses.
"""
from __future__ import annotations

import argparse
import os

import uvicorn
from uvicorn.protocols.http.h11_impl import H11Protocol


class HeaderDeadlineProtocol(H11Protocol):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._header_timer = None
        self._waiting_headers = False
        self._state = args[1] if len(args) > 1 else kwargs['server_state']

    def _stop_header_wait(self):
        if self._header_timer is not None:
            self._header_timer.cancel()
            self._header_timer = None
        if self._waiting_headers:
            self._waiting_headers = False
            self._state.pending_headers -= 1

    def _start_header_wait(self):
        if self._waiting_headers:
            return True # Partial data never extends the absolute deadline.
        count = getattr(self._state, 'pending_headers', 0)
        if count >= getattr(self.config, 'max_pending_headers', 256):
            self.transport.close()
            return False
        self._waiting_headers = True
        self._state.pending_headers = count + 1
        self._header_timer = self.loop.call_later(
            getattr(self.config, 'header_deadline', 15.0), self._expire_headers,
        )
        return True

    def _expire_headers(self):
        self._stop_header_wait()
        self.transport.close()

    def connection_made(self, transport):
        super().connection_made(transport)
        self._start_header_wait()

    def data_received(self, data):
        if self.cycle is None or self.cycle.response_complete:
            if not self._start_header_wait():
                return
        super().data_received(data)
        if (self.cycle is not None and not self.cycle.response_complete) or self.transport.get_protocol() is not self:
            self._stop_header_wait()

    def connection_lost(self, exc):
        self._stop_header_wait()
        super().connection_lost(exc)


def run():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--host', default='0.0.0.0')
    parser.add_argument('--port', type=int, default=int(os.environ.get('CELL_AGENT_PORT') or '9100'))
    args = parser.parse_args()
    uvicorn.run('main:app', host=args.host, port=args.port, http=HeaderDeadlineProtocol)


if __name__ == '__main__':
    run()
