import sys
from pathlib import Path


ANALYSIS_AGENT_DIR = Path(__file__).resolve().parents[1]
ANALYSIS_AGENT_DIR_STR = str(ANALYSIS_AGENT_DIR)

if ANALYSIS_AGENT_DIR_STR not in sys.path:
    sys.path.insert(0, ANALYSIS_AGENT_DIR_STR)
