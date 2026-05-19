from __future__ import annotations


class Ds2Gateway:
    """Reserved DS2 integration boundary.

    Phase 1 intentionally does not connect to DS2.
    """

    enabled = False

    def status(self) -> str:
        return "DS2 架構已預留，尚未啟用。"

