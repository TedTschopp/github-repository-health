"""Evidence-led repository health assessment engine.

The public interface is deliberately small so GitHub Actions and report
renderers can use the engine without depending on its implementation details.
"""

from .engine import ENGINE_VERSION, assess_repository, write_assessment

__all__ = ["assess_repository", "write_assessment"]
__version__ = ENGINE_VERSION
