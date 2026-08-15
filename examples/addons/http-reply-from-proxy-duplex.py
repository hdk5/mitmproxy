"""Handle a request and response as a bi-directional stream."""

from collections.abc import Iterable

from mitmproxy import http
from mitmproxy.script import run_in_thread


def requestheaders(flow: http.HTTPFlow) -> None:
    if flow.request.pretty_url != "http://example.com/path":
        return

    def start_request() -> None:
        """Start processing the request and its headers."""
        raise NotImplementedError()

    def write_request(chunk: bytes) -> None:
        """Process a request-body chunk."""
        raise NotImplementedError()

    def finish_request() -> None:
        """Finish processing the request body."""
        raise NotImplementedError()

    def start_response(*, block: bool) -> http.Response | None:
        """Return the response once it has started.

        With ``block=False``, return immediately with ``None`` if the response
        has not started yet. Otherwise, wait until the response starts.
        """
        raise NotImplementedError()

    def read_response(*, block: bool) -> Iterable[bytes]:
        """Yield response-body chunks, followed by ``b""`` at response EOM.

        With ``block=False``, yield currently available data and return without
        waiting for more. Otherwise, wait for data and continue through
        response EOM.
        """
        raise NotImplementedError()

    # mitmproxy calls this once when request headers are received (`None`), once
    # for each request-body chunk, and once when the request ends (`b""`).
    #
    # Before request EOM, process the request data and return promptly: response
    # data should only be yielded when it is already available. After request
    # EOM, the returned iterable may block while waiting for the remainder of
    # the response.
    #
    # Set flow.response before yielding any response data. Yielding b"" marks
    # response EOM, but does not stop request processing: if the response ends
    # early, stream() will still receive the remaining request data. Once
    # request EOM has been received, the response must also be completed by
    # yielding b"" unless it has already ended.
    @run_in_thread
    def stream(chunk: bytes | None) -> Iterable[bytes]:
        if chunk is None:
            # This is the first call, after request headers have been received.
            start_request()
        elif chunk == b"":
            # This is the last call, after request EOM.
            # Request trailers are also available in flow.request.trailers.
            finish_request()
        else:
            # This is a request-body chunk.
            write_request(chunk)

        block = chunk == b""

        if not flow.response:
            response = start_response(block=block)
            if response is None:
                return []
            if flow.request.is_http11:
                response.headers["transfer-encoding"] = "chunked"
                # or, alternatively:
                # response.headers["content-length"] = "12345"
            flow.response = response

        return read_response(block=block)

    flow.stream = stream
