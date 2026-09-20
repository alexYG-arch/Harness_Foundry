"""Generic reviewed-build product identity; historical kernels are not public APIs."""

from .identity import FACTORY_ID, FACTORY_VERSION, TARGET_PROTOCOL_VERSION

__version__ = FACTORY_VERSION


__all__ = [
    "FACTORY_ID",
    "FACTORY_VERSION",
    "TARGET_PROTOCOL_VERSION",
    "__version__",
]
