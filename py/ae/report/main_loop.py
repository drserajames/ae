# Ported from vcm (ssm-report tooling) py/vcm/v2/main_loop.py — Phase 1 engine/library tier.
# async command loop + kateri task. See py/ae/report/MIGRATION.md.
"""
ae.report.main_loop — the async command loop and command-marking decorators.

`main_loop()` is the entry point a report driver script calls: it parses the CLI, starts
the kateri and socket-server tasks (unless the chosen command opts out), and runs a
`MainLoop`. Commands are ordinary methods on the driver's commander marked with the
`@command` decorator; `@no_kateri`, `@headless` and `@no_loop` tune how the loop runs them.
`MainLoop` runs the command once and, unless `@no_loop`, keeps running — a
`MainModuleWatcher` reloads changed source and re-runs. Ported from the vcm ssm-report
tooling.
"""
import sys
import os
import tempfile
import asyncio
from pathlib import Path
from typing import Callable, NoReturn

from ae.utils import kateri
import ae.utils.traceback
from .modules import Modules

# ======================================================================

def main_loop(start_kateri: bool = True) -> NoReturn:
    """Entry point for a report driver script: parse the CLI (`--command-list`, or a command
    name plus `-e/--exit-on-exception`), chdir to the driver's directory, spin up the kateri
    + socket-server tasks (unless the command is `@no_kateri`, or is a `@headless` batch
    command and the native map renderer is selected), and run the async `MainLoop`. Exits the
    process; never returns normally."""

    commander = Modules.commander()

    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--command-list", action='store_true', default=False)
    parser.add_argument("command", nargs='?')
    parser.add_argument("-e", "--exit-on-exception", action='store_true', default=False)
    args = parser.parse_args()
    if args.command_list:
        print("\n".join(list_commands(commander, order=["style", "export", "adjust", "prestyle", "download", "populate"])))
        sys.exit(0)
    if args.command:
        os.chdir(Path(sys.argv[0]).parent)
        # P2: with the native map renderer selected (AE_REPORT_MAP_RENDERER unset/native) the
        # *batch* commands run kateri-free — their map-PDF, styled.ace and sig-page-mapi kateri
        # round-trips are all replaced by in-process native code (see map_renderer.py) — so do
        # NOT launch the kateri app / socket server for them. Those are exactly the @headless
        # commands (`export`, `serum_coverage_export`, …): @headless already means "batch PDF
        # export, no visible window needed". The interactive commands (`style`,
        # `serum_coverage`) are NOT @headless and still need a real kateri to display and drag
        # points in, whatever the map-render backend is — kateri remains the interactive
        # viewer. The opt-in kateri backend keeps launching it for everything, as before.
        from .map_renderer import native_selected
        cmd = getattr(commander, args.command)
        no_kateri_cmd = getattr(cmd, "main_loop_no_kateri", False)
        headless = getattr(cmd, "main_loop_headless", False)
        if start_kateri and not no_kateri_cmd and not (headless and native_selected()):
            tasks: list[Task] = [kateri.KateriTask(headless=headless), kateri.SocketServerTask()]
        else:
            tasks: list[Task] = []
        main_loop = MainLoop(command=args.command, exit_on_exception=args.exit_on_exception)
        main_loop.run(tasks)
    else:
        sys.exit(1)

# ======================================================================

_command_attr = "main_loop_command"

def command(cmd: Callable) -> Callable:
    "decorator to mark function as a command for main_loop"
    setattr(cmd, _command_attr, True)
    return cmd

def is_command(name: str, parent=None) -> bool:
    """Whether attribute `name` on `parent` (default `__main__`) is marked `@command`."""
    if parent is None:
        parent = sys.modules["__main__"]
    return getattr(getattr(parent, name), _command_attr, False)

def list_commands(parent=None, order: list[str]=[]) -> list[str]:
    """Sorted list of command names on `parent` (default `__main__`), with the names in
    `order` placed first."""
    if parent is None:
        parent = sys.modules["__main__"]

    def key(cmd_name: str):
        """Sort key placing `order` commands first (in order), then alphabetically."""
        try:
            ind = order.index(cmd_name)
        except ValueError:
            ind = len(order)
        return f"{ind}-{cmd_name}"

    return sorted((attribute for attribute in dir(parent) if is_command(name=attribute, parent=parent)), key=key)

def no_kateri(cmd: Callable) -> Callable:
    "decorator to avoid running kateri when command is called"
    cmd.main_loop_no_kateri = True
    return cmd

def headless(cmd: Callable) -> Callable:
    """decorator to launch kateri headless (window parked off-screen, app kept out of the
    Dock/menu-bar) for batch PDF-export commands — no window pop-up or focus steal. Do NOT use
    on interactive commands (style/adjust) that need a visible, draggable window. It also marks
    the command as "needs no visible kateri", which `main_loop` uses to skip launching kateri
    altogether when the native map renderer is selected."""
    cmd.main_loop_headless = True
    return cmd

def no_loop(cmd: Callable) -> Callable:
    "decorator to stop loop after running the command"
    cmd.main_loop_stop = True
    return cmd

# ======================================================================

# base class for tasks, e.g. kateri
class Task:
    """Base class for the loop's async tasks (e.g. kateri, socket server). Subclasses
    override `start` and `running`."""

    async def start(self, **kwargs):
        """Start the task"""
        print(f">> Task.start: override in derived class {self.__name__}", file=sys.stderr)

    def running(self) -> bool:
        """Return if task was running, i.e. socket communication initialized"""
        print(f">> Task.running: override in derived class {self.__name__}", file=sys.stderr)
        return False

    def name(self):
        """Display name of the task (its class)."""
        return self.__class__

# ----------------------------------------------------------------------

class MainLoop (Modules):
    """The report's async run loop (a `Modules` subclass): runs the requested command once,
    then — unless the command is `@no_loop` — watches source files and re-runs on change."""

    def __init__(self, command: str, exit_on_exception: bool = False):
        """Set the command name to run and whether command/reload errors should propagate
        rather than be reported."""
        super().__init__(exit_on_exception=exit_on_exception)
        self.command = command
        self.stop = False

    async def do(self):
        """Run the command (awaiting it if it is a coroutine) and set `stop` from its
        `@no_loop` marker. Reports — or, with `exit_on_exception`, re-raises — any error."""
        try:
            cmd = getattr(self.main_module().commander(), self.command)
            if asyncio.iscoroutinefunction(cmd):
                await cmd()
            else:
                cmd()
            self.stop = getattr(cmd, "main_loop_stop", False)
        except Exception:  # as err:
            if self.exit_on_exception:
                raise
            else:
                ae.utils.traceback.report_exception()

    def run(self, tasks: list[Task]) -> NoReturn:
        """Create a temporary Unix socket and run the async `main` under asyncio; exit the
        process when it finishes or on Ctrl-C."""
        with tempfile.TemporaryDirectory() as td:
            self.socket_name = os.path.join(td, 'sock')
            try:
                asyncio.run(self.main(tasks))
            except Exception as err:
                raise
                print(f"> Error: {err}", file=sys.stderr)
                if self.exit_on_exception:
                    sys.exit(1)
            except KeyboardInterrupt:
                print(">>> [zero_do.MainLoop] terminated by Ctrl-C", file=sys.stderr)
            sys.exit(0)

    async def main(self, tasks: list[Task]):
        """Start the given tasks plus a `MainModuleWatcher`, wait for the first to finish,
        cancel the rest, and re-raise any task exception."""
        running_tasks = [asyncio.create_task(task.start(main_loop=self, socket_name=self.socket_name), name=task.name()) for task in tasks + [MainModuleWatcher(tasks)]]
        done, pending = await asyncio.wait(running_tasks, return_when=asyncio.FIRST_COMPLETED)
        for task in pending:
            task.cancel()
        for task in done:
            if exc := task.exception():
                raise exc

    def _get_command(self) -> callable:
        return getattr(self.module, self.command)

# ----------------------------------------------------------------------

class MainModuleWatcher (Task):
    """Task that waits for the other tasks (kateri) to come up, runs the command once, then
    polls for source changes and reloads until the loop is told to stop."""

    def __init__(self, dependencies: list[Task]):
        """Record the tasks to wait on before running the command."""
        self.dependencies = dependencies

    async def start(self, main_loop: MainLoop, **ignored):
        """Wait for the dependency tasks to be running, run the command once, then loop
        reloading changed modules until `main_loop.stop`."""
        # wait for tasks (e.g. kateri) to activate
        while not all(dep.running() for dep in self.dependencies):
            await asyncio.sleep(0.1)
        await main_loop.do()
        while not main_loop.stop:
            await asyncio.sleep(0.5)
            await main_loop.reload_modules_if_updated()

# ======================================================================
