"""Handle a request and response as a bidirectional asynchronous stream."""

import asyncio
from collections.abc import AsyncIterable

from mitmproxy import http


def requestheaders(flow: http.HTTPFlow) -> None:
    if flow.request.pretty_url != "http://example.com/path":
        return

    def start_request() -> None:
        """Start processing the request and its headers."""
        raise NotImplementedError()

    async def write_request(chunk: bytes) -> None:
        """Process a request-body chunk."""
        raise NotImplementedError()

    async def finish_request() -> None:
        """Finish the request after its body and trailers have arrived."""
        raise NotImplementedError()

    async def start_response() -> http.Response:
        """Wait until the response headers are available."""
        raise NotImplementedError()

    async def read_response() -> AsyncIterable[bytes]:
        """Yield response-body chunks and set response trailers before returning."""
        raise NotImplementedError()
        yield b""  # pragma: no cover

    async def stream(request_body: AsyncIterable[bytes]) -> AsyncIterable[bytes]:
        start_request()

        async def send_request() -> None:
            async for chunk in request_body:
                await write_request(chunk)
            # Request trailers are now available in flow.request.trailers.
            await finish_request()

        request_task = asyncio.create_task(send_request())
        try:
            flow.response = await start_response()
            flow.response.raw_content = None

            async def response_body():
                try:
                    async for chunk in read_response():
                        yield chunk
                    # Set flow.response.trailers in read_response() before it returns.
                finally:
                    if not request_task.done():
                        request_task.cancel()

            return response_body()
        except BaseException:
            request_task.cancel()
            raise

    flow.stream = stream
