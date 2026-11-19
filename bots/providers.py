"""Content providers. No model calls occur in mock/manual mode.

Implement these protocols in a separate adapter when enabling an LLM.
The adapter must not approve drafts, publish content, or access payment credentials.
"""
from typing import Protocol

class ResearchProvider(Protocol):
    async def answer(self, question: str) -> str: ...

class SummaryProvider(Protocol):
    async def suggest(self, snapshot: str) -> str: ...

MOCK = ('**MOCK RESEARCH — FICTIONAL DEMO ONLY**\n'
        'Northstar Robotics is invented. Revenue is $42 million, up 18%; '
        'software represents 28% of revenue. The top three customers account for 52%. '
        'Two pilots may convert, but approvals could slip by two quarters. '
        'Watch customer concentration, pilot conversion, software share, margins, and cash burn. '
        'This is a fixed demo response, not live analysis or investment advice.')


class MockResearchProvider:
    async def answer(self, question: str) -> str:
        return MOCK

class ManualSummaryProvider:
    async def suggest(self, snapshot: str) -> str:
        raise NotImplementedError("Manual mode: the administrator supplies the free summary.")
