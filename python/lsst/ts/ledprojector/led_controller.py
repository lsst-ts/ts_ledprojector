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

__all__ = ["LEDController"]
import asyncio
import inspect
import logging
import types
from typing import Any, Callable, Dict, List, Union

import yaml

# Hide mypy error `Module "labjack" has no attribute "ljm"`.
from labjack import ljm  # type: ignore
from lsst.ts import utils
from lsst.ts.ess.labjack import BaseLabJackDataClient
from lsst.ts.xml.enums.LEDProjector import LEDBasicState

# DRA-CN024D05 SSR requires 3.0VDC minimum turn-on voltage, up to 12 VDC max
# 1.0VDC minimum turn-off voltage
# all ports should be digital IO so write 1 for on/0 for off
# Values to write to labjack for operating LED


# EIO0-3 are flexible digital IO lines
# EIO4-7 are dedicated digital IO lines
# CIO0-3 are dedicated digital IO lines


# Time limit for communicating with the LabJack (seconds).
COMMUNICATION_TIMEOUT = 5

# Time limit for configuring streaming;
# measured time from far away is 6 seconds.
START_STREAMING_TIMEOUT = 15

# Maximum frequency (Hz) at which the mock simulator can read an input.
# The max read frequency per channel = MAX_MOCK_READ_FREQUENCY / num channels.
MAX_MOCK_READ_FREQUENCY = 10000


class LabjackChannel:
    def __init__(
        self,
        serialNumber: str,
        channel: str,
        index: int = -1,
        status: LEDBasicState = LEDBasicState.UNKNOWN,
    ):
        self.serial = serialNumber
        self.channel = channel
        self.index = index
        self.status = status

        self.offset_dict = {
            "AIN": 0,
            "DIO": 2000,
            "FIO": 2000,
            "EIO": 2008,
            "CIO": 2016,
            "MIO": 2020,
        }

    # Here we automatically convert labjack channel names
    # to their modbus address
    def address(self) -> int:
        addNum = int(self.channel[3:])

        # AIN are 32-bit wide, so their address takes up 2
        # addresses for the LSB/MSB
        if self.channel[:3] == "AIN":
            addNum *= 2
        else:
            # all other DIO is standard 16-bit wide transmission
            addNum += self.offset_dict[self.channel[:3]]
        return addNum


class LEDController(BaseLabJackDataClient):
    """Class to handle switching of LEDs connected to Labjack Interface

    Parameters
    ----------
    config : `types.SimpleNamespace`
        LED-specific configuration.
    log : `logging.Logger`
        Logger.
    labjack : 'LabJackInterface'
        The defined interface class to the labjack that LEDs are connected to.
    labjack_port : 'string'
        The string name of the Labjack port that this LED is connected to.
    led_name : 'string'
        String of the serial number for this LED model.
    status_callback : `awaitable` or `None`, optional
        Coroutine to call when evt_ledState or evt_ledConnected changes.
        It receives one argument: this model.
    simulate : `bool`, optional
        Run in simulation mode?
    make_connect_time_out : `bool`, optional
        Make the connect method timeout?
        Only useful for unit tests.
        Ignored if simulate false.

    Raises
    ------
    TypeError
        If ``status_callback`` is not None and not a coroutine.
    ValueError
        If ``config.default_power`` not in range [800, 1200], inclusive.

    Attributes
    ----------
    default_power : `float`
        Default power after the led is started (Watts) in range 800-1200.
    led_was_on : `bool`
        Was the led commanded on, as of the most recently read LabJack data?
    """

    def __init__(
        self,
        config: types.SimpleNamespace,
        log: logging.Logger | None = None,
        status_callback: Callable | None = None,
        simulate: bool = False,
        make_connect_time_out: bool = False,
    ) -> None:
        super().__init__(
            config=config, topics=config.topics, log=log, simulation_mode=simulate
        )

        if status_callback is not None and not inspect.iscoroutinefunction(
            status_callback
        ):
            raise TypeError(
                f"status_callback={status_callback} must be None or a coroutine"
            )

        self.config = config
        self.log = (
            log.getChild(type(self).__name__)
            if log is not None
            else logging.getLogger(type(self).__name__)
        )
        self.make_connect_time_out = make_connect_time_out
        self.status_callback = status_callback

        # TODO: better names
        # We want a multiple key -> 1 value list for easy parsing
        # We are creating a dictionary with 3 keys -> 1 value
        # 1st key : Serial number of the LED
        # 2nd key : 0-indexed list placement of the LED
        # 3rd key : Labjack Channel Name of that LED
        # First, make a list of tuples for the relevant info from the config
        for topic in self.config.topics:
            if topic["topic_name"] == "ledControllerItem":
                led_topic = topic
        led_names = led_topic["led_names"]
        channel_names = led_topic["channel_names"]

        self.log.info(f"Opening led_controller with led names {led_names}")
        self.log.info(f"Opening led_controller with channel names {channel_names}")

        tmp = list(zip(led_names, channel_names))
        # Now make a list of labjackchannel objs using the previous list's info
        # Note that we use enumerate to get the numerical index
        a = [
            LabjackChannel(serialNumber=data[0], channel=data[1], index=ind)
            for ind, data in enumerate(tmp, start=0)
        ]
        # Now create our multi-key dictionary
        # TODO: write unit test for this dictionary setup
        self.channels: Dict[Union[str, int], LabjackChannel] = {}
        for lbc in a:
            self.channels.update({lbc.serial: lbc})
            self.channels.update({lbc.index: lbc})
            self.channels.update({lbc.channel: lbc})

        self.log.info(f"led_controller dictionary {self.channels}")

        # Set if connected to the labjack and state data seen,
        # cleared otherwise.
        self.status_event = asyncio.Event()
        self.status_task = utils.make_done_future()

    @classmethod
    def get_config_schema(cls) -> dict[str, Any]:
        return yaml.safe_load(
            """
$schema: http://json-schema.org/draft-07/schema#
description: Schema for LEDController
type: object
properties:
  device_type:
    description: LabJack model
    type: string
    default: T7
  connection_type:
    description: Connection type
    type: string
    default: TCP
  identifier:
    description: >-
        LabJack indentifier:
        * A host name or IP address if connection_type = TCP or WIFI
        * A serial number if connection_type = USB
        * For testing in an environment with only one LabJack you may use ANY
    type: string
  poll_interval:
    description: Polling interval (seconds)
    type: number
    default: 1
  topics:
    description: >-
      Array of batches of relevant sensors.
    type: array
    minItems: 1
    items:
      types: object
      minItems: 1
      properties:
        topic_name:
            description: Casual name for the sensor cluster.
            type: string
        sensor_name:
            description: Value for the sensor_name field of the topic.
            type: string
        location:
            description: >-
                Location of sensors. A comma-separated list, with one item per non-null channel_name.
            type: string
        led_names:
            description: >-
                Names of LEDs for identification, such as the serial number.
            type: array
            minItems: 1
            items:
              type: string
        channel_names:
            description: >-
                LabJack channel names, in order of the field array.
            type: array
            minItems: 1
            items:
              type: string
      required:
        - topic_name
        - sensor_name
        - location
        - led_names
        - channel_names
required:
  - device_type
  - connection_type
  - identifier
  - poll_interval
additionalProperties: false
"""
        )

    async def run(self) -> None:
        """Read data from the LabJack."""
        while True:
            # TODO: properly handle return
            # TODO: write unit test on that return handling
            # data_dict =
            await self.run_in_thread(
                func=self._blocking_read, timeout=COMMUNICATION_TIMEOUT
            )

            # Support unit testing with a future the test can reset.
            self.wrote_event.set()
            await asyncio.sleep(self.config.poll_interval)

    def get_state(
        self,
        identifier: str | int,
    ) -> LEDBasicState:
        """Get the current LEDBasicState of the LED.

        Parameters
        ----------
        identifier : `str` | `int`
            Serial number of LED or 0-indexed identifier
        status : `LEDBasicState`
            Status to set the LED to.

        Returns
        -------
        state : `LEDBasicState`
            State of requested LED.

        Raises
        ------
        RuntimeError
            If identifier is not valid
        """
        # TODO: maybe change this to try/except or osmething else?
        if identifier in self.channels:
            return self.channels[identifier].status
        else:
            raise RuntimeError("Given identifier doesn't exist")

    async def set_state(self, identifier: str | int, status: LEDBasicState) -> None:
        """Set status and, if changed, call the status callback.

        Parameters
        ----------
        identifier : `str` | `integer`
            Serial number of LED or 0-indexed identifier
        status : `LEDBasicState`
            Status to set the LED to.

        Raises
        ------
        RuntimeError
            If identifier is not valid
        """
        # TODO: maybe change this to try/except or osmething else?
        if identifier in self.channels:
            if self.channels[identifier].status is not status:
                self.channels[identifier].status = status
                await self.call_status_callback()
        else:
            raise RuntimeError("Given identifier doesn't exist")

    async def switch_led(
        self,
        identifier: str | int,
        ledSetting: LEDBasicState,
    ) -> None:
        """Switch the LED on/off.

        Parameters
        ----------
        identifier : `str` | `int`
            The serial number of the LED, port of the labjack,
            or a 0-indexed identifier
        ledSetting : `boolean`
            true to switch LED on, false to switch LED

        Raises
        ------
        RuntimeError
            If the Labjack cannot connect
        """
        # TODO: Do we need separate on/off functions?

        # Check we are not already in that state.
        if self.get_state(identifier) == ledSetting:
            self.log.warning(f"LED {identifier} is already {ledSetting}")
            return

        # TODO: Maybe we just raise error if handle isn't explicitly connected?
        if self.handle is None:
            try:
                self.log.info("Attempting to connect to Labjack...")
                self._blocking_connect()
            except RuntimeError:
                raise RuntimeError("Labjack can't connect")

        # switch the LED.
        # TODO: do we need to check return here?
        self.log.info(f"Switching LED {identifier} to {ledSetting}")
        ljm.eWriteAddress(
            self.handle,
            self.channels[identifier].address(),
            ljm.constants.INT32,
            int(ledSetting),
        )

        # Update state
        await self.set_state(identifier, ledSetting)

    async def switch_multiple_leds(
        self, identifiers: List[Union[str, int]], ledStates: List[LEDBasicState]
    ) -> None:
        """Switch multiple LEDs at once.

        Parameters
        ----------
        identifiers : `string` | `int`
            A list of serial numbers and/or 0-indexed identifiers
            of the LEDs to switch
        ledStates : `boolean`
            A list of boolean states for the LEDs to be switched,
            true for on, false for off

        Raises
        ------
        RuntimeError
            If the Labjack cannot connect
            If the len of identifiers & ledStates is not equal.
        """
        if len(identifiers) != len(ledStates):
            raise RuntimeError(
                "Length of identifiers and states in switch_multiple_leds doesn't match."
            )

        # Get rid of LEDs that are already set
        # TODO: probably more efficient to just get rid of this
        # TODO: and send it anyway
        for count, identifier in enumerate(identifiers, start=0):
            if self.get_state(identifier) == ledStates[count]:
                self.log.warning(f"LED {identifier} is already {ledStates[count]}")
                # Note that even though we might be
                # deleting an element of the list
                # The count will update as well so we
                # will not go out of bounds
                del identifiers[count]
                del ledStates[count]

        # TODO: Maybe we just raise error if handle isn't explicitly connected?
        if self.handle is None:
            try:
                self.log.info("Attempting to connect to Labjack...")
                self._blocking_connect()
            except RuntimeError:
                raise RuntimeError("Labjack can't connect")

        # Turn on the LED.
        # TODO: probably should check the ewrite return val
        self.log.info(f"Switching LEDs {identifiers} to {ledStates}")
        ljm.eWriteAddresses(
            self.handle,
            len(identifiers),
            [self.channels[identifier].address() for identifier in identifiers],
            [ljm.constants.INT32 for x in ledStates],
            [(int(x)) for x in ledStates],
        )

        # Update state
        for count, identifier in enumerate(identifiers, start=0):
            await self.set_state(identifier, ledStates[count])

    async def call_status_callback(self) -> None:
        """
        Call the status callback, if there is one.
        """
        if self.status_callback is None:
            return
        try:
            await self.status_callback()
        except Exception:
            self.log.exception("status callback failed")

    def _blocking_connect(self) -> None:
        """
        Connect and then read the specified channels.

        This makes sure that the configured channels can be read.

        Raises
        ------
        RuntimeError
            If each input channel configured at creation of this class,
            does not return a value from the labjack, i.e. configuration
            is not valid.
        """
        super()._blocking_connect()

        # Configure flexible IO to digital
        # The DIO_INHIBIT hex is what qualifies something as being digital.
        # 0 bit = digital. Read from LSB, ex: FIO0 is bit 0
        # TODO: do we need to have a smart parsing function
        # TODO: to parse flexible IO, or can we just hardcode?
        # TODO: if hardcoding, does hardcoding all as 0 (digital) work?
        ljm.eWriteName(self.handle, "DIO_INHIBIT", 0x00000)
        ljm.eWriteName(self.handle, "DIO_ANALOG_ENABLE", 0x00000)

        # Read each input channel, to make sure the configuration is valid.
        input_channel_names = set(lbc.channel for lbc in self.channels.values())
        num_frames = len(input_channel_names)
        values = ljm.eReadNames(self.handle, num_frames, input_channel_names)
        if len(values) != len(input_channel_names):
            raise RuntimeError(
                f"len(input_channel_names)={input_channel_names} != len(values)={values}"
            )
