"""finagent: a 10-K financial analyst agent with page citations and verified arithmetic."""
from .agent import AnalystAgent
from .ingest import Filing, load_bytes, load_file
from .schemas import AgentAnswer, LineItem

__version__ = "0.1.0"
__all__ = ["AgentAnswer", "AnalystAgent", "Filing", "LineItem", "__version__", "load_bytes", "load_file"]
