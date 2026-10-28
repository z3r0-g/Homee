"""UI route blueprints."""

from .bots import bots_bp
from .skills import skills_bp
from .mcps import mcps_bp
from .knowledge import knowledge_bp
from .settings import settings_bp

__all__ = [
    "bots_bp",
    "skills_bp",
    "mcps_bp",
    "knowledge_bp",
    "settings_bp",
]
