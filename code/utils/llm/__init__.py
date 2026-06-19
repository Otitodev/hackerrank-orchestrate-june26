"""Provider-agnostic vision-LLM layer.

Import the abstract interface + factory only; vendor adapters import their SDK
lazily so missing SDKs never break the package.
"""

from .base import ImageBlock, LLMClient, ModelConfig, Usage, extract_json  # noqa: F401
from .factory import make_client  # noqa: F401
