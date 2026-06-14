#!/usr/bin/env python3
"""Offline verification of the interactive adjust glue (MIGRATION.md Stage B).

`ae.adjust.adjust_from_kateri` is the human-facing half of the adjust stage: an
operator drags points in kateri (which only *moves* points, never relaxes) and
presses "Relax". The ae side pulls back the edited chart and relaxes it with
**all points free** — the dragged positions are not pinned, only better *starting*
coordinates that help the optimiser escape a local optimum — **capturing the
optimiser's intermediate layouts** and streaming them back as `LAYT` frames so
kateri animates the relax. Each frame is Kabsch-aligned to the pre-relax layout
(MDS picks an arbitrary gauge); the last frame is marked `final` and commits.

A live kateri needs a GUI socket, so here we stand in fakes and verify, on
synthetic test/chart1.ace:

  * the relax streams several `LAYT` frames, exactly the last marked `final`;
  * the animation starts at the operator's dragged layout (Kabsch anchors frame 0);
  * the dragged points are NOT held fixed — they move by the final frame;
  * relax lowers the stress of the perturbed layout;
  * `Communicator.get_moved_points()` still round-trips (informational only);
  * the full `RLAX` → `LAYT`-stream round trip works through the real
    `Communicator.connected()` read loop.

Run::  PYTHONPATH=build:py python3 test/adjust_from_kateri.py
"""

import sys, asyncio, json
from pathlib import Path

_root = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(_root / "build"), str(_root / "py")]

import ae_backend.chart_v3
from ae.adjust import adjust_from_kateri


def _close(a, b, tol=1e-6):
    return a is not None and b is not None and abs(a[0] - b[0]) < tol and abs(a[1] - b[1]) < tol


def _load_relaxed():
    "chart1.ace ships with no projection; relax so there is something to adjust."
    chart = ae_backend.chart_v3.Chart(str(_root / "test" / "chart1.ace"))
    chart.relax(number_of_dimensions=2, number_of_optimizations=10, minimum_column_basis="none")
    chart.keep_projections(1)
    return chart


class FakeCommunicator:
    "Stands in for ae.utils.kateri.Communicator — captures the streamed LAYT frames."

    def __init__(self, chart):
        self._chart = chart
        self.frames = []        # list of (coords, final)

    async def get_chart(self):
        return self._chart

    async def get_moved_points(self):
        return []

    def send_layout(self, coords, final):
        self.frames.append((coords, final))

    async def drain(self):
        pass


async def test_glue():
    chart = _load_relaxed()
    layout = chart.projection(0).layout()
    npoints = len(layout)
    # Simulate the operator dragging two antigens to far-off coordinates — this
    # perturbs the layout and inflates its stress.
    dragged_to = {0: [5.0, 5.0], 3: [-5.0, -5.0]}
    for pno, xy in dragged_to.items():
        layout[pno] = xy
    start = [list(layout[i]) if layout[i] is not None else None for i in range(npoints)]
    dragged_stress = chart.projection(0).recalculate_stress()   # stress of the perturbed layout

    comm = FakeCommunicator(chart)
    adj = await adjust_from_kateri(comm, max_frames=30, frame_delay=0.0)
    frames = comm.frames

    # 1. several frames streamed, exactly the last marked final
    assert len(frames) >= 2, f"expected a multi-frame stream, got {len(frames)}"
    assert frames[-1][1] is True, "last frame must be final"
    assert all(f[1] is False for f in frames[:-1]), "only the last frame may be final"

    # 2. each frame is the full layout, one [x,y] per point (None preserved)
    for coords, _final in frames:
        assert len(coords) == npoints

    # 3. the animation starts at what the operator sees (frame 0 ~ dragged layout,
    #    because the first intermediate IS the start and Kabsch(start,start) ~ identity)
    for pno, xy in dragged_to.items():
        assert _close(frames[0][0][pno], xy, tol=1e-3), \
            f"first frame point {pno} {frames[0][0][pno]} should start at the drag {xy}"

    # 4. the dragged points are NOT pinned — they moved by the final frame
    for pno, xy in dragged_to.items():
        assert not _close(frames[-1][0][pno], xy, tol=1e-2), \
            f"dragged point {pno} did not move during the free relax"

    # 5. relax (all points free) lowered the stress of the perturbed layout
    assert adj.stress() < dragged_stress, \
        f"relax did not lower stress: dragged={dragged_stress:.2f} -> relaxed={adj.stress():.2f}"

    print(f"OK [test_glue]: streamed {len(frames)} LAYT frames (last=final), animation anchored at "
          f"drag start, points moved freely, stress {dragged_stress:.2f} -> {adj.stress():.4f}")


# ----------------------------------------------------------------------
# End-to-end through the real Communicator.connected() read loop.
#
# FakeKateri plays kateri's side of the socket: it is the StreamWriter the
# Communicator writes to (parsing the length-prefixed COMD/LAYT frames the ae side
# emits) AND it feeds the StreamReader the replies — a CHRT for get_chart, a JSON
# for get_moved_points — and it captures the LAYT frames the ae side streams. The
# operator pressing "Relax" is simulated by feeding the bare 4-byte RLAX code.
# ----------------------------------------------------------------------

class FakeKateri:

    def __init__(self, chart, moved=()):
        self.reader = asyncio.StreamReader()
        self._chart = chart
        self._moved = list(moved)
        self._buf = bytearray()
        self.frames = []                 # list of dicts {"l": [...], "final": bool}
        self.final_seen = asyncio.Event()

    # -- StreamWriter side (ae → kateri) --------------------------------
    def write(self, data):
        self._buf += data
        self._parse()

    async def drain(self):
        pass

    def close(self):
        pass

    # -- helpers --------------------------------------------------------
    def _feed_frame(self, code: bytes, payload: bytes):
        "Feed a length-prefixed reply frame into the reader (mirrors Communicator._send)."
        self.reader.feed_data(code)
        self.reader.feed_data(len(payload).to_bytes(4, sys.byteorder))
        self.reader.feed_data(payload)
        if last := len(payload) % 4:
            self.reader.feed_data(b"\x00" * (4 - last))

    def _parse(self):
        "Pull complete length-prefixed frames out of the write buffer and react."
        while len(self._buf) >= 8:
            code = bytes(self._buf[0:4])
            length = int.from_bytes(self._buf[4:8], sys.byteorder)
            pad = (4 - length % 4) % 4
            total = 8 + length + pad
            if len(self._buf) < total:
                break
            payload = bytes(self._buf[8:8 + length])
            del self._buf[:total]
            if code == b"COMD":
                command = json.loads(payload).get("C")
                if command == "get_chart":
                    self._feed_frame(b"CHRT", bytes(self._chart.export()))
                elif command == "get_moved_points":
                    self._feed_frame(b"JSON", json.dumps(
                        {"C": "get_moved_points", "moved": self._moved}).encode("utf-8"))
            elif code == b"LAYT":
                frame = json.loads(payload)
                self.frames.append(frame)
                if frame.get("final"):
                    self.final_seen.set()


async def test_get_moved_points():
    "get_moved_points is informational-only now; verify it still round-trips."
    from ae.utils.kateri import Communicator
    fake = FakeKateri(_load_relaxed(), moved=[2, 5, 7])
    comm = Communicator()
    conn = asyncio.create_task(comm.connected(fake.reader, fake))
    while not comm.is_connected():            # let connected() set self.writer
        await asyncio.sleep(0)
    moved = await asyncio.wait_for(comm.get_moved_points(), timeout=10)
    assert moved == [2, 5, 7], f"get_moved_points returned {moved}"
    fake.reader.feed_data(b"QUIT")
    fake.reader.feed_eof()
    await asyncio.wait_for(conn, timeout=5)
    print(f"OK [test_get_moved_points]: round-tripped informational moved list {moved}")


async def test_rlax_roundtrip():
    from ae.utils.kateri import Communicator
    chart = _load_relaxed()
    layout = chart.projection(0).layout()
    dragged_to = {0: [5.0, 5.0], 3: [-5.0, -5.0]}
    for pno, xy in dragged_to.items():
        layout[pno] = xy

    fake = FakeKateri(chart)
    comm = Communicator()
    conn = asyncio.create_task(comm.connected(fake.reader, fake))

    # operator pressed "Relax": a bare 4-byte RLAX notification (no length, no payload)
    fake.reader.feed_data(b"RLAX")

    # the read loop dispatches handle_relax, which pulls get_chart through this same
    # loop, relaxes (all points free) capturing intermediates, and streams LAYT frames.
    await asyncio.wait_for(fake.final_seen.wait(), timeout=60)

    # close the connection cleanly
    fake.reader.feed_data(b"QUIT")
    fake.reader.feed_eof()
    await asyncio.wait_for(conn, timeout=5)

    assert len(fake.frames) >= 2, f"expected a multi-frame stream, got {len(fake.frames)}"
    assert fake.frames[-1]["final"] is True, "last frame must be final"
    assert all(not f["final"] for f in fake.frames[:-1]), "only the last frame may be final"
    # dragged points are free — they moved by the final frame
    final_layout = fake.frames[-1]["l"]
    for pno, xy in dragged_to.items():
        got = final_layout[pno]
        assert got is not None and (abs(got[0] - xy[0]) > 1e-2 or abs(got[1] - xy[1]) > 1e-2), \
            f"dragged point {pno} was held fixed through RLAX — it should be free to move"
    print(f"OK [test_rlax_roundtrip]: RLAX → free relax → streamed {len(fake.frames)} LAYT frames "
          f"(last=final) through the real connected() loop, points moved freely")


async def main():
    await test_glue()
    await test_get_moved_points()
    await test_rlax_roundtrip()


if __name__ == "__main__":
    asyncio.run(main())
