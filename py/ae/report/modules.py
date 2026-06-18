# Ported from vcm (ssm-report tooling) 2026-0119-tc2/py/vcm/v2/modules.py — Phase 1 engine/library tier.
# hot-reload module machinery. See py/ae/report/MIGRATION.md.
import sys, datetime, traceback
from pathlib import Path
import importlib.util, importlib.machinery
import inspect

import ae.utils.traceback

# ======================================================================

class Modules:

    def __init__(self, exit_on_exception: bool = False):
        self._main_module = sys.modules['__main__']
        self._main_module_path = self._main_module.__file__
        self._modules_to_reload = None
        self.exit_on_exception = exit_on_exception

    def main_module(self):
        return self._main_module

    def modules_to_reload(self):
        if not self._modules_to_reload:
            self._modules_to_reload = [{"m": mod, "t": Path(mod.__file__).stat().st_mtime} for name, mod in sys.modules.items() if getattr(mod, "__file__", None) and not mod.__file__.startswith("/opt/homebrew")]
        return self._modules_to_reload

    async def reload_modules_if_updated(self):

        reloading_printed = False

        def reloading_message():
            nonlocal reloading_printed
            if not reloading_printed:
                print(f">>>> reloading [{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}]", file=sys.stderr)
                reloading_printed = True

        mod_reloaded = False
        for mod_en in self.modules_to_reload():
            mod_mtime = Path(mod_en["m"].__file__).stat().st_mtime
            if mod_en["t"] != mod_mtime:
                if mod_en['m'].__name__ != "__main__":
                    reloading_message()
                    print(f">>>>    {mod_en['m'].__name__} from {mod_en['m'].__file__}", file=sys.stderr)
                    importlib.reload(mod_en['m'])
                    self.reload_referencing(mod_en['m'].__name__, {"__main__"})  # have to reload all modules that use mod_en
                self.reload_main_module()
                mod_en["t"] = mod_mtime
                mod_reloaded = True
        if mod_reloaded:
            await self.do()

    def reload_referencing(self, name: str, reloaded: set[str]):
        just_reloaded = []
        for mod_en2 in self.modules_to_reload():
            if mod_en2['m'].__name__ not in reloaded:  # break infinite loop of modules referencing each other
                for attr2 in dir(mod_en2['m']):
                    if inspect.ismodule(mod3 := getattr(mod_en2['m'], attr2)) and mod3.__name__ == name:
                        print(f">>>>        {mod_en2['m'].__name__} from {mod_en2['m'].__file__}", file=sys.stderr)
                        importlib.reload(mod_en2['m'])
                        reloaded.add(mod_en2['m'].__name__)
                        just_reloaded.append(mod_en2['m'].__name__)
        for mod4_n in just_reloaded:
            self.reload_referencing(mod4_n, reloaded)

    def reload_main_module(self):
        try:
            print(f">>>>    __main__ {self._main_module_path}", file=sys.stderr)
            main_module_name = Path(self._main_module_path).stem
            if spec := importlib.util.spec_from_file_location(main_module_name, self._main_module_path, loader=importlib.machinery.SourceFileLoader(main_module_name, str(self._main_module_path))):
                self._main_module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(self.main_module())
            else:
                raise RuntimeError(f"importlib.util.spec_from_file_location failed for \"{self._main_module_path}\"")
        except:
            if self.exit_on_exception:
                raise
            else:
                ae.utils.traceback.report_exception()

    @classmethod
    def commander(cls):
        return sys.modules['__main__'].commander()

# ======================================================================
