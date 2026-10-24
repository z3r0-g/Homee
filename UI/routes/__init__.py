"""UI route blueprints."""

from .bots import bots_bp
from .personalities import personalities_bp
from .mcps import mcps_bp
from .knowledge import knowledge_bp
from .settings import settings_bp
from .agents import agents_bp

__all__ = [
    "bots_bp",
    "personalities_bp",
    "mcps_bp",
    "knowledge_bp",
    "settings_bp",
    "agents_bp",
]