"""SuperQR V7 production sender components.

V7 keeps the physically validated V6 carrier/geometry while upgrading the
payload density and transport. There is one SuperQR application; this package
contains the current sender engine, not a separate application.
"""

from .sender import V7SenderSession

__all__ = ["V7SenderSession"]
