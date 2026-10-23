"""A minimal LSP client for the tests: starts `tabula lsp` and talks JSON-RPC over its stdin/stdout."""
import json
import os
import queue
import subprocess
import sys
import threading
import time
from pathlib import Path

CLI = Path(__file__).resolve().parents[1] / "cli"


class Client:
    def __init__(self, root: Path, init_options=None, encodings=("utf-16",)):
        env = {**os.environ, "PYTHONPATH": str(CLI) + os.pathsep + os.environ.get("PYTHONPATH", "")}
        self.p = subprocess.Popen([sys.executable, "-m", "tabula", "lsp"], stdin=subprocess.PIPE,
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env, cwd=str(root))
        self.next_id = 0
        self.msgs: "queue.Queue" = queue.Queue()
        self.diagnostics: dict = {}
        self.notes: list = []
        threading.Thread(target=self._read, daemon=True).start()
        r = self.request("initialize", {"processId": os.getpid(), "rootUri": root.as_uri(),
                                        "capabilities": {"general": {"positionEncodings": list(encodings)},
                                                         "textDocument": {"hover": {"contentFormat": ["markdown"]}}},
                                        "initializationOptions": init_options or {}})
        self.capabilities = r["capabilities"]
        self.notify("initialized", {})

    def _read(self):
        f = self.p.stdout
        while True:
            line = f.readline()
            if not line:
                return
            length = 0
            while line.strip():
                if line.lower().startswith(b"content-length:"):
                    length = int(line.split(b":")[1])
                line = f.readline()
            msg = json.loads(f.read(length))
            if msg.get("method") == "textDocument/publishDiagnostics":
                self.diagnostics[msg["params"]["uri"]] = msg["params"]["diagnostics"]
            elif "id" in msg and "method" in msg:                 # a request from the server: answer it
                self._send({"jsonrpc": "2.0", "id": msg["id"], "result": None})
            elif "method" in msg:
                self.notes.append(msg)
            else:
                self.msgs.put(msg)

    def _send(self, msg):
        body = json.dumps(msg).encode("utf-8")
        self.p.stdin.write(b"Content-Length: %d\r\n\r\n" % len(body) + body)
        self.p.stdin.flush()

    def notify(self, method, params):
        self._send({"jsonrpc": "2.0", "method": method, "params": params})

    def request(self, method, params, timeout=15):
        self.next_id += 1
        rid = self.next_id
        self._send({"jsonrpc": "2.0", "id": rid, "method": method, "params": params})
        end = time.time() + timeout
        while time.time() < end:
            try:
                msg = self.msgs.get(timeout=0.1)
            except queue.Empty:
                continue
            if msg.get("id") == rid:
                if "error" in msg:
                    raise RuntimeError(msg["error"]["message"])
                return msg.get("result")
        raise TimeoutError(method)

    def open(self, path: Path, text: str):
        self.notify("textDocument/didOpen", {"textDocument": {"uri": path.as_uri(), "languageId": "tabula",
                                                              "version": 1, "text": text}})

    def change(self, path: Path, text: str, version: int):
        self.notify("textDocument/didChange", {"textDocument": {"uri": path.as_uri(), "version": version},
                                               "contentChanges": [{"text": text}]})

    def wait_diagnostics(self, path: Path, cond=lambda d: True, timeout=15):
        end = time.time() + timeout
        while time.time() < end:
            d = self.diagnostics.get(path.as_uri())
            if d is not None and cond(d):
                return d
            time.sleep(0.05)
        raise TimeoutError(f"diagnostics for {path}: {self.diagnostics.get(path.as_uri())}")

    def at(self, path: Path, line: int, character: int):
        return {"textDocument": {"uri": path.as_uri()}, "position": {"line": line, "character": character}}

    def close(self):
        try:
            self.request("shutdown", None, timeout=5)
            self.notify("exit", None)
            self.p.wait(timeout=5)
        except Exception:
            self.p.kill()
