"""Test package.

The one thing done here is claiming the system Visual C++ runtime before
anything imports PyQt5, exactly as the launchers do. Without it, running the
render tests alone and running them alongside the editor tests disagree about
which copy of the runtime the process holds, and onnxruntime loads in one case
and not the other. A no-op off Windows. See util/msvc_runtime.py.
"""

import os

from util.msvc_runtime import prepare

prepare()

# The fixtures are Japanese source text translated into English, whatever the
# developer's .env says. util.translation loads .env without overriding, so
# pinning here keeps a local source_language=English or language=Russian from
# changing expected results.
os.environ["source_language"] = "Japanese"
os.environ["language"] = "English"
os.environ["deepseekReasoning"] = "off"
