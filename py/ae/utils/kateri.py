import sys, os, shutil, asyncio, subprocess, json
from pathlib import Path
from typing import Optional, Callable, Any

import ae_backend.chart_v3

# ======================================================================

# Resolve the symlink (e.g. /usr/local/bin/kateri) to the real in-bundle
# executable. macOS dyld derives @executable_path from the path passed to exec,
# NOT the resolved symlink, so launching via the symlink makes
# @executable_path/../Frameworks point at a non-existent dir and kateri fails to
# load its Flutter frameworks. Launching via the real bundle path fixes this.
_kateri = shutil.which("kateri")
KATERI_EXE = os.path.realpath(_kateri) if _kateri else "kateri"

# ----------------------------------------------------------------------

class KateriTask:

    def __init__(self):
        self.kateri = None

    async def start(self, socket_name: str, **ignored):
        try:
            self.kateri = await asyncio.create_subprocess_exec(KATERI_EXE, "--socket", socket_name)
            print(f">>> [Kateri] started", file=sys.stderr)
            retcode = await self.kateri.wait()
            print(f">>> [Kateri] finished with code {retcode}", file=sys.stderr)
        except asyncio.CancelledError:
            self.kateri.terminate()
            self.kateri = None

    def running(self) -> bool:
        return self.kateri is not None

    def name(self):
        return self.__class__

# ----------------------------------------------------------------------

class SocketServerTask:

    def __init__(self):
        self.socket_server = None
        self.communicator = None

    async def start(self, socket_name: str, **ignored):
        global communicator
        self.socket_server = await asyncio.start_unix_server(communicator.connected, socket_name)
        print(f">>> [server-for-kateri] started pid: {os.getpid()} socket: {socket_name}", file=sys.stderr)
        await self.socket_server.serve_forever()
        self.socket_server = None
        print(f">>> [server-for-kateri] completed", file=sys.stderr)

    def running(self) -> bool:
        global communicator
        return self.socket_server is not None and communicator is not None and communicator.is_connected()

    def name(self):
        return self.__class__

# ----------------------------------------------------------------------

class Communicator:

    def __init__(self):
        self.writer: asyncio.StreamWriter = None
        self.expected = []
        self._command_id: int = 0

    def reset(self):
        """Clear per-session connection state. `communicator` is a module-level singleton reused
        across kateri sessions (e.g. one signature-page render per lab in a single driver process,
        each its own `asyncio.run`). `connected()` sets `self.writer` but the previous session's
        teardown — `quit()` then loop close — is not guaranteed to null it before the next session
        starts. A leftover `self.writer` makes `is_connected()` report True immediately, so the next
        session skips its connect-wait and sends the chart/pdf commands to the dead writer → the new
        kateri instance sits idle and the render stalls at map 0. Call this before each session so the
        connect-wait actually waits for the new kateri to connect."""
        self.writer = None
        self.expected = []
        self._command_id = 0

    def send_ace(self, filename: Path):
        self._send(b"CHRT", subprocess.check_output(["decat", str(filename)]))

    def send_chart(self, chart: ae_backend.chart_v3.Chart):
        self._send(b"CHRT", chart.export())

    def send_layout(self, coords: list, final: bool):
        """Send a `LAYT` frame for live relax animation: the full layout in raw projection
        coordinates (one `[x, y]` per point, `null` for disconnected), same order/length as
        the chart layout. kateri applies the projection transform + a fixed recenter and
        repaints, keeping its viewport/plot-style/selection stable. `final=True` commits the
        coordinates into kateri's model (so a later `get_chart` returns the relaxed layout)."""
        self._send(b"LAYT", json.dumps({"l": coords, "final": final}).encode("utf-8"))

    async def drain(self):
        "Flush the write buffer (used between streamed LAYT frames)."
        if self.writer:
            await self.writer.drain()

    def set_style(self, style: str):
        self.send_command({"C": "set_style", "style": style})

    def export_to_legacy(self, style: Optional[str] = None):
        if style:
            self.send_command({"C": "set_style", "style": style})
        self.send_command({"C": "export_to_legacy"})

    async def get_chart(self) -> ae_backend.chart_v3.Chart:
        futu = asyncio.get_running_loop().create_future()
        self.send_command_expect(command={"C": "get_chart"}, expect={"C": "CHRT", "future": futu})
        return await futu

    async def get_viewport(self) -> dict:
        futu = asyncio.get_running_loop().create_future()
        self.send_command_expect(command={"C": "get_viewport"}, expect={"C": "JSON", "future": futu})
        viewport = await futu
        return viewport

    async def get_moved_points(self) -> list[int]:
        "layout indices the operator dragged in kateri (antigens 0..nAg-1, then sera), sorted+deduplicated"
        futu = asyncio.get_running_loop().create_future()
        self.send_command_expect(command={"C": "get_moved_points"}, expect={"C": "JSON", "future": futu})
        result = await futu
        return result.get("moved", [])

    async def get_pdf(self, style: str = None, width: float = 800.0) -> bytes:
        if style:
            self.set_style(style=style)
        futu = asyncio.get_running_loop().create_future()
        self.send_command_expect(command={"C": "pdf", "width": width}, expect={"C": "PDFB", "future": futu})
        return await futu

    # def pdf(self, filename: str|Path, style: str = None, width: float = 800.0, open: bool = False):
    #     if style:
    #         self.set_style(style=style)
    #     self.send_command_expect(command={"C": "pdf", "width": width}, expect={"C": "PDFB", "filename": filename, "open": open})

    def quit(self):
        self.send_command({"C": "quit"})

    def send_command_expect(self, command: dict[str, Any], expect: dict[str, Any]):
        command_id = self.send_command(command=command)
        self.expected.append({**expect, "_id": command_id})

    def send_command(self, command: dict[str, Any]) -> int:
        "return sent command id"
        import json
        # print(f">>>> send to kateri \"{json.dumps(command)}\"", file=sys.stderr)
        self._command_id += 1
        self._send(b"COMD", json.dumps({**command, "_id": self._command_id}).encode("utf-8"))
        return self._command_id

    def _send(self, data_code: bytes, data: bytes):
        if not self.writer:
            raise RuntimeError("communicator is not connected")
        self.writer.write(data_code)
        self.writer.write(len(data).to_bytes(4, byteorder=sys.byteorder))
        self.writer.write(data)
        # sent data must contain number of bytes divisible by 4
        if last_chunk := len(data) % 4:
            self.writer.write(b"\x00" * (4 - last_chunk))
        # if data_code == b"COMD":
        #     print(f">>>> sent data {data_code} {len(data)} bytes {data} with padding {4 - last_chunk}", file=sys.stderr)

    async def connected(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        self.writer = writer
        while (request := (await reader.read(4)).decode('utf8').strip()) not in ["", "QUIT"]: # empty request means broken pipe
            # print(f">>>> received from kateri: {request}", file=sys.stderr)
            if request == "HELO":
                pass
            elif request == "RLAX":
                # operator pressed Relax in kateri — bare 4-byte code, no length/payload (like HELO/QUIT).
                # pin the moved points and relax, then push the result back. Run as a task so this read
                # loop keeps draining — the get_chart/get_moved_points replies come back through it.
                asyncio.create_task(handle_relax(self))
            elif request in ["PDFB", "CHRT", "JSON"]:
                payload_length = int.from_bytes(await reader.read(4), byteorder=sys.byteorder)
                # print(f">>>> [kateri.Communicator] {request} {payload_length} bytes", file=sys.stderr)
                self._process_expected(request, await self._read_with_padding(reader=reader, payload_length=payload_length))
            else:
                print(f">> [kateri.Communicator] unrecognized request \"{request}\"", file=sys.stderr)
            await writer.drain()
        print(f">>>> kateri: quit", file=sys.stderr)
        writer.close()

    def is_connected(self) -> bool:
        return self.writer is not None

    async def _read_with_padding(self, reader: asyncio.StreamReader, payload_length: int):
        data = bytes()
        left = payload_length
        while left > 0:
            chunk = await reader.read(left)
            # print(f">>>> [kateri.Communicator] read {len(chunk)} of {left}", file=sys.stderr)
            data += chunk
            left -= len(chunk)
        if (padding := 4 - payload_length % 4) != 4:
            await reader.read(padding)
        return data

    def _process_expected(self, code: str, data: bytes):
        for no, en in enumerate(self.expected):
            if en["C"] == code:
                self._process_expected_request(expected=en, data=data)
                self.expected[no:no+1] = []
                break;

    def _process_expected_request(self, expected: dict[str, Any], data: bytes):
        if expected["C"] == "PDFB":
            print(f">>> [kateri.Communicator] receiving pdf ({len(data)} bytes)", file=sys.stderr)
            if futu := expected.get("future"):
                futu.set_result(data)
        elif expected["C"] == "CHRT":
            print(f">>> [kateri.Communicator] receiving chart ({len(data)} bytes)", file=sys.stderr)
            if futu := expected.get("future"):
                futu.set_result(ae_backend.chart_v3.chart_from_json(data))
        elif expected["C"] == "JSON":
            print(f">>> [kateri.Communicator] receiving json ({len(data)} bytes)", file=sys.stderr)
            if futu := expected.get("future"):
                futu.set_result(json.loads(data))
        else:
            print(f">> [kateri.Communicator] not implemented processing for expected {expected}", file=sys.stderr)

# ----------------------------------------------------------------------

async def handle_relax(comm: "Communicator"):
    """Handle a kateri `RLAX` notification (operator pressed Relax after dragging):
    pull the edited chart, relax it with **all points free** (the dragged positions
    are only better starting coordinates, not pinned) while capturing the optimiser's
    intermediate layouts, and stream those back as `LAYT` frames so kateri animates the
    relax (last frame commits the layout). Implemented by `ae.adjust.adjust_from_kateri`
    (imported lazily to keep this transport module free of the adjust/ae_backend/numpy
    dependency at import time). Runs as a task off `connected()`'s read loop — it streams
    frames with `await`s between them while the loop keeps draining `get_chart`'s reply —
    so exceptions are logged here rather than lost."""
    from ae.adjust import adjust_from_kateri
    try:
        await adjust_from_kateri(comm)   # send_back=True by default → the relaxed map reappears in kateri
    except Exception:
        import traceback
        print(">> [kateri.Communicator] handle_relax failed:", file=sys.stderr)
        traceback.print_exc()

# ----------------------------------------------------------------------

communicator = Communicator()

# ======================================================================
