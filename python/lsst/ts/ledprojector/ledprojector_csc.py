# This file is part of ts_ledprojector.
#
# Developed for the Vera C. Rubin Observatory Telescope and Site Systems.
# This product includes software developed by the LSST Project
# (https://www.lsst.org).
# See the COPYRIGHT file at the top-level directory of this distribution
# for details of code ownership.
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.

__all__ = ["LEDProjectorCsc", "run_ledprojector"]

import asyncio
import types
from typing import Any, List, Union

from lsst.ts import salobj
from lsst.ts.xml.enums.LEDProjector import LEDBasicState

from . import __version__
from .config_schema import CONFIG_SCHEMA
from .led_controller import LEDController


class LEDProjectorCsc(salobj.ConfigurableCsc):
    """LED Projector controller

    Parameters
    ----------
    config_dir : `None` or `str`, optional
        Directory of configuration files, or None for the standard
        configuration directory (obtained from `_get_default_config_dir`).
        This is provided for unit testing.
    initial_state : `State` or `int`, optional
        The initial state of the CSC. This is provided for unit testing,
        as real CSCs should start up in `State.STANDBY`, the default.
    override : `str`, optional
        Configuration override file to apply if ``initial_state`` is
        `State.DISABLED` or `State.ENABLED`.
    simulation_mode : `bool`, optional
        Simulation mode; one of:

        * False for normal operation
        * True for simulation

    Attributes
    ----------
    led_controller : `LEDController`
        The controller representing the labjack controller
        which is controlling the leds.
    """

    version = __version__
    valid_simulation_modes = (0, 1)

    def __init__(
        self,
        config_dir: None | str = None,
        initial_state: salobj.State = salobj.State.STANDBY,
        override: str = "",
        simulation_mode: bool = False,
    ) -> None:
        self.led_controller = None
        self.should_be_connected = False

        self.config = None

        super().__init__(
            name="LEDProjector",
            index=0,
            config_schema=CONFIG_SCHEMA,
            config_dir=config_dir,
            initial_state=initial_state,
            override=override,
            simulation_mode=simulation_mode,
        )

    @staticmethod
    def get_config_pkg() -> str:
        return "ts_config_mtcalsys"

    @property
    def controller_connected(self) -> bool:
        """Return True if the LabJack is connected"""
        return self.led_controller is not None and self.led_controller.connected

    async def configure(self, config: Any) -> None:
        """Configure the CSC"""
        self.config = config

    async def handle_summary_state(self) -> None:
        """Override of the handle_summary_state function to
        create led controller object when enabled

        Raises
        ------
        ValueError
            If config is None
        """
        self.log.info(f"handle_summary_state {salobj.State(self.summary_state).name}")
        if self.disabled_or_enabled:
            if self.led_controller is None:
                if self.should_be_connected:
                    return self.fault(
                        code=LEDBasicState.Error,
                        report="led controller should be connected but isn't.",
                    )
                else:
                    if self.config is None:
                        raise ValueError(
                            "CSC tried to create LEDController with config equal to None"
                        )
                    self.led_controller = LEDController(
                        config=self.config,
                        log=self.log,
                        simulate=self.simulation_mode,
                    )
            await self.connect_led()
        else:
            await self.disconnect_led()

    async def connect_led(self) -> None:
        """Connect to the LabJack and get status.
        This method initiates the LEDController as well

        Raises
        ------
        ValueError
            If there is no LEDController object
        asyncio.TimeoutError
            If it takes longer than self.config.led.connect_timeout
        """
        await self.disconnect_led()
        if self.led_controller is None:
            raise ValueError("CSC Tried to use led controller without a valid object")

        await asyncio.wait_for(
            self.led_controller.connect(),
            timeout=self.led_controller.COMMUNICATION_TIMEOUT,
        )
        self.should_be_connected = True

    # TODO should we be catching errors
    async def disconnect_led(self) -> None:
        """Disconnect to the LabJack & delete the LEDController object

        Raises
        ------
        Exception
            If disconnect failed
        """
        try:
            if self.led_controller is None:
                return
            await self.led_controller.disconnect()
        except Exception as e:
            self.log.warning(f"Failed to disconnect led; continuing: {e!r}")

        # Delete the led controller because the config may change.
        self.led_controller = None
        self.should_be_connected = False

    async def close_tasks(self) -> None:
        """Close the CSC gratefully.

        Disconnects the labjack, deletes LEDController object
        Then closes tasks.

        """
        await self.disconnect_led()
        await super().close_tasks()

    async def do_switchAllOff(self, data: types.SimpleNamespace) -> None:
        """Switch off all LEDs.

        Parameters
        ----------
        data : salobj.BaseMsgType
            Command data; ignored.

        Raises
        ----------
        salobj.ExpectedError
            If labjack isnt connected first
        """
        self.assert_enabled()
        if self.led_controller is None:
            raise salobj.ExpectedError("Labjack not connected")
        await self.led_controller.switch_all_leds_off()

    async def do_switchAllOn(self, data: types.SimpleNamespace) -> None:
        """Switch on all LEDs.

        Parameters
        ----------
        data : salobj.BaseMsgType
            Command data; ignored.

        Raises
        ----------
        salobj.ExpectedError
            If labjack isnt connected first
        """
        self.assert_enabled()
        if self.led_controller is None:
            raise salobj.ExpectedError("Labjack not connected")
        await self.led_controller.switch_all_leds_on()

    async def switch_leds(
        self, identifiers: List[Union[str, int]], onOff: LEDBasicState
    ) -> None:
        """Switch multiple LEDs at once.

        Parameters
        ----------
        identifiers : `list of str or int`
            A list of serial numbers and/or 0-indexed identifiers
            of the LEDs to switch
        onOff : `LEDBasicState`
            Turn the list of LEDs ON or OFF

        Raises
        ----------
        salobj.ExpectedError
            If labjack isnt connected first
        """
        if self.led_controller is None:
            raise salobj.ExpectedError("Labjack not connected")
        await self.led_controller.switch_multiple_leds(identifiers, onOff)

    # TODO can this even do multiple LEDs?
    async def do_switchOn(self, data: types.SimpleNamespace) -> None:
        """Switch on one or more LEDs.

        Parameters
        ----------
        data : salobj.BaseMsgType
            Command data; list of any combination of the numeric index,
            LED serial number, or the labjack port to turn on.
        """
        self.assert_enabled()

        await self.switch_leds(
            data.identifiers, [LEDBasicState.ON for _ in data.identifiers]
        )

    async def do_switchOff(self, data: types.SimpleNamespace) -> None:
        """Switch off one or more specific led.

        Parameters
        ----------
        data : salobj.BaseMsgType
            Command data; list of any combination of the numeric index,
            LED serial number, or the labjack port to turn off.
        """
        self.assert_enabled()

        await self.switch_leds(
            data.identifiers, [LEDBasicState.OFF for _ in data.identifiers]
        )


def run_ledprojector() -> None:
    """Run the LEDProjector CSC."""
    asyncio.run(LEDProjectorCsc.amain(index=None))
