# Ported from vcm (ssm-report tooling) 2026-0119-tc2/py/vcm/v2/main_loop.py — Phase 1 engine/library tier.
# async command loop + kateri task. See py/ae/report/MIGRATION.md.
import sys
import os
import tempfile
import asyncio
# import datetime
from pathlib import Path
from typing import Callable, NoReturn

from ae.utils import kateri
import ae.utils.traceback
from .modules import Modules

# ======================================================================

def main_loop(start_kateri: bool = True) -> NoReturn:

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
        if start_kateri and not getattr(getattr(commander, args.command), "main_loop_no_kateri", False):
            tasks: list[Task] = [kateri.KateriTask(), kateri.SocketServerTask()]
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
    if parent is None:
        parent = sys.modules["__main__"]
    return getattr(getattr(parent, name), _command_attr, False)

def list_commands(parent=None, order: list[str]=[]) -> list[str]:
    if parent is None:
        parent = sys.modules["__main__"]

    def key(cmd_name: str):
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

def no_loop(cmd: Callable) -> Callable:
    "decorator to stop loop after running the command"
    cmd.main_loop_stop = True
    return cmd

# ======================================================================

# base class for tasks, e.g. kateri
class Task:

    async def start(self, **kwargs):
        """Start the task"""
        print(f">> Task.start: override in derived class {self.__name__}", file=sys.stderr)

    def running(self) -> bool:
        """Return if task was running, i.e. socket communication initialized"""
        print(f">> Task.running: override in derived class {self.__name__}", file=sys.stderr)
        return False

    def name(self):
        return self.__class__

# ----------------------------------------------------------------------

class MainLoop (Modules):

    def __init__(self, command: str, exit_on_exception: bool = False):
        super().__init__(exit_on_exception=exit_on_exception)
        self.command = command
        self.stop = False

    async def do(self):
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

    def __init__(self, dependencies: list[Task]):
        self.dependencies = dependencies

    async def start(self, main_loop: MainLoop, **ignored):
        # wait for tasks (e.g. kateri) to activate
        while not all(dep.running() for dep in self.dependencies):
            await asyncio.sleep(0.1)
        await main_loop.do()
        while not main_loop.stop:
            await asyncio.sleep(0.5)
            await main_loop.reload_modules_if_updated()

# ======================================================================
