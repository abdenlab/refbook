"""Make the pipeline importable, so the pure parts of its steps can be tested.

Shared modules (engine, layout, observe) import by name. Numbered steps
(10_roots.py, ...) are not valid module names, so tests load them with step().
"""

import importlib.util
import sys
from pathlib import Path

PIPELINE = Path(__file__).resolve().parent.parent / "pipeline"
sys.path.insert(0, str(PIPELINE))


def step(name: str):
    """A numbered pipeline step as a module, e.g. step("10_roots")."""
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, PIPELINE / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module
