"""Static server for the probe site plus POST /log, which appends to probe_log.jsonl."""
import functools
import http.server
import pathlib
import sys

SITE = pathlib.Path(sys.argv[1])
LOG = pathlib.Path(sys.argv[2])


class Handler(http.server.SimpleHTTPRequestHandler):
    extensions_map = {**http.server.SimpleHTTPRequestHandler.extensions_map,
                      '.mjs': 'text/javascript', '.js': 'text/javascript',
                      '.wasm': 'application/wasm'}

    def do_POST(self):
        n = int(self.headers.get('Content-Length', 0))
        body = self.rfile.read(n).decode('utf-8', 'replace')
        ua = self.headers.get('User-Agent', '')
        with LOG.open('a') as f:
            f.write(body.replace('\n', ' ') + '\t' + ua + '\n')
        self.send_response(204)
        self.end_headers()


http.server.ThreadingHTTPServer(('127.0.0.1', int(sys.argv[3])),
                                functools.partial(Handler, directory=str(SITE))).serve_forever()
