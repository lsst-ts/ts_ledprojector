__all__ = ["command_ledprojector"]

import asyncio

from lsst.ts import salobj


class LEDProjectorCommander(salobj.CscCommander):
    """LEDProjector commander.

    Parameters
    ----------
    enable : bool
        Enable the CSC when first connecting to it?
    """

    def __init__(self, enable: bool) -> None:
        super().__init__(
            name="LEDProjector",
            index=0,
            enable=enable,
        )


def command_ledprojector() -> None:
    """Run the LEDProjector commander."""
    asyncio.run(LEDProjectorCommander.amain(index=None))
