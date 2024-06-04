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
from .led_controller import COMMUNICATION_TIMEOUT, LEDController


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
            index=None,
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
            If Led Controller should be connected but isn't
        """
        self.log.info(f"handle_summary_state {salobj.State(self.summary_state).name}")
        if self.disabled_or_enabled and self.led_controller is None:
            if self.should_be_connected:
                await self.fault(
                    code=LEDBasicState.Error,
                    report="led controller should be connected but isn't.",
                )
                raise RuntimeError("LED Controller should be connected but isn't")
            elif self.config is None:
                raise RuntimeError(
                    "Tried to create LEDController without a configuration. "
                    "This is most likely a bug with the control sequence causing "
                    "the configuration step to be skipped. Try sending the CSC back "
                    "to STANDBY or OFFLINE and restarting it. You should report this issue."
                )
            self.led_controller = LEDController(
                config=self.config,
                log=self.log,
                simulate=self.simulation_mode,
            )
        if self.disabled_or_enabled:
            await self.connect_led()
        else:
            await self.disconnect_led()

    async def connect_led(self) -> None:
        """Connect to the LabJack and get status.
        This method initiates the LEDController as well

        Raises
        ------
        RuntimeError
            If there is no LEDController object
        asyncio.TimeoutError
            If it takes longer than self.config.led.connect_timeout
        """
        # if self.controller_connected:
        #     await self.disconnect_led()
        if self.led_controller is None:
            raise RuntimeError("CSC Tried to use led controller without a valid object")

        async with asyncio.timeout(COMMUNICATION_TIMEOUT):
            await self.led_controller.connect()
        self.should_be_connected = True

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
        led_serials = await self.led_controller.switch_all_leds_off()
        for sn in led_serials:
            await self.evt_ledState.set_write(
                index=0,
                serialNumber=sn,
                ledBasicState=self.led_controller.channels[sn].status,
                value=self.led_controller.channels[sn].dac_value,
            )

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
        led_serials = await self.led_controller.switch_all_leds_on()
        for sn in led_serials:
            await self.evt_ledState.set_write(
                index=0,
                serialNumber=sn,
                ledBasicState=self.led_controller.channels[sn].status,
                value=self.led_controller.channels[sn].dac_value,
            )

    async def switch_leds(
        self, identifiers: List[Union[str, int]], on_off: LEDBasicState
    ) -> None:
        """Switch multiple LEDs at once.

        Parameters
        ----------
        identifiers : `list of str or int`
            A list of serial numbers and/or 0-indexed identifiers
            of the LEDs to switch
        on_off : `LEDBasicState`
            Turn the list of LEDs ON or OFF

        Raises
        ----------
        salobj.ExpectedError
            If labjack isnt connected first
        """
        self.assert_enabled()
        if self.led_controller is None:
            raise salobj.ExpectedError("Labjack not connected")
        await self.led_controller.switch_multiple_leds(identifiers, on_off)

    async def do_adjustDACPower(self, data: types.SimpleNamespace) -> None:
        """Adjust voltage on all LEDs.

        Parameters
        ----------
        serialNumbers : `str`
            List of Serial number of LED to adjust.
        dacValues : `float``
            List of DAC Value 0-5V, 1.2mV resolution

        Raises
        ----------
        salobj.ExpectedError
            If labjack isnt connected first
        """

        self.assert_enabled()
        if self.led_controller is None:
            raise salobj.ExpectedError("Labjack not connected")

        serialNumbers = data.serialNumbers.split(",")
        dacValues = [float(value) for value in data.dacValues.split(",")]

        await self.led_controller.adjust_dac_values(
            identifiers=serialNumbers,
            values=dacValues,
        )

        for sn in serialNumbers:
            await self.evt_ledState.set_write(
                serialNumber=sn,
                ledBasicState=self.led_controller.channels[sn].status,
                value=self.led_controller.channels[sn].dac_value,
            )

    async def do_adjustAllDACPower(self, data: types.SimpleNamespace) -> None:
        """Adjust voltage on all DAC Channels.

        Parameters
        ----------
        dacValue : `float``
            DAC Value 0-5V, 1.2mV resolution

        Raises
        ----------
        salobj.ExpectedError
            If labjack isnt connected first
        """

        self.assert_enabled()
        if self.led_controller is None:
            raise salobj.ExpectedError("Labjack not connected")

        dacValue = data.dacValue

        await self.led_controller.adjust_all_dac_values(
            value=dacValue,
        )

        channels = self.led_controller.channels

        for channel in channels.values():
            await self.evt_ledState.set_write(
                serialNumber=channel.serial,
                ledBasicState=channel.status,
                value=channel.dac_value,
            )

    async def do_switchOn(self, data: types.SimpleNamespace) -> None:
        """Switch on one or more LEDs.

        Parameters
        ----------
        data : salobj.BaseMsgType
            Command data; list of any combination of the numeric index,
            LED serial number, or the labjack port to turn on.
        """
        self.assert_enabled()
        if self.led_controller is None:
            raise salobj.ExpectedError("Labjack not connected")

        serialNumbers = data.serialNumbers.split(",")

        await self.switch_leds(
            serialNumbers, [LEDBasicState.ON for _ in range(len(serialNumbers))]
        )

        for sn in serialNumbers:
            await self.evt_ledState.set_write(
                serialNumber=sn,
                ledBasicState=self.led_controller.channels[sn].status,
                value=self.led_controller.channels[sn].dac_value,
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
        if self.led_controller is None:
            raise salobj.ExpectedError("Labjack not connected")

        serialNumbers = data.serialNumbers.split(",")

        await self.switch_leds(
            serialNumbers, [LEDBasicState.OFF for _ in range(len(serialNumbers))]
        )

        for sn in serialNumbers:
            await self.evt_ledState.set_write(
                serialNumber=sn,
                ledBasicState=self.led_controller.channels[sn].status,
                value=self.led_controller.channels[sn].dac_value,
            )


def run_ledprojector() -> None:
    """Run the LEDProjector CSC."""
    asyncio.run(LEDProjectorCsc.amain(index=None))
