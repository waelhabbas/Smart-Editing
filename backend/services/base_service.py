"""Abstract base class for content-type services."""

from abc import ABC, abstractmethod


class BaseService(ABC):
    """Base class for all service types (Explainer, Breaking News, etc.)."""

    @abstractmethod
    async def process_step1(self, **kwargs) -> dict:
        """Process step 1: video + template -> base timeline."""
        ...

    @abstractmethod
    async def process_step2(self, **kwargs) -> dict:
        """Process step 2: media files -> final timeline + SRT."""
        ...
