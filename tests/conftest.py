import importlib.util
import importlib.machinery
import pathlib
import sys

script_path = pathlib.Path(__file__).parent.parent / "claude-session-namer"
loader = importlib.machinery.SourceFileLoader("session_namer", str(script_path))
spec = importlib.util.spec_from_loader("session_namer", loader)
mod = importlib.util.module_from_spec(spec)
loader.exec_module(mod)
sys.modules["session_namer"] = mod
