"""Local origin server for the request-stream concurrency benchmark."""

import argparse
from http.server import BaseHTTPRequestHandler
from http.server import ThreadingHTTPServer


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def do_GET(self) -> None:
        if self.path != "/fast":
            self.send_error(404)
            return

        body = b"fast\n"
        self.send_response(200)
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self) -> None:
        if self.path != "/slow":
            self.send_error(404)
            return

        content_length = int(self.headers.get("content-length", "0"))
        body = self.rfile.read(content_length)
        response = f"received {len(body)} bytes\n".encode()
        self.send_response(200)
        self.send_header("content-length", str(len(response)))
        self.end_headers()
        self.wfile.write(response)

    def log_message(self, _format: str, *_args: object) -> None:
        pass


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=18090)
    args = parser.parse_args()

    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    server.daemon_threads = True
    print(f"Origin listening on http://127.0.0.1:{args.port}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
