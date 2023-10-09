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
import functools
import logging
import types
from typing import Any, Dict, List, Union

import yaml

# Hide mypy error `Module "labjack" has no attribute "ljm"`.
from labjack import ljm  # type: ignore
from lsst.ts import utils
from lsst.ts.ess.labjack import BaseLabJackDataClient
from lsst.ts.xml.enums.LEDProjector import LEDBasicState

# Time limit for communicating with the LabJack (seconds).
COMMUNICATION_TIMEOUT = 5


class LabjackChannel:
    """Class that represents a single port on the labjack.

    Parameters
    -------
    serial_number : `str`
        Serial number of product on the labjack channel.
    channel : `str`
        Channel of the labjack, e.g. AIO0, DIO5, etc...
    index : `int`, optional
        Numerical index, used for enumerating and parsing multiple chans
        default -1
    status : `LEDBasicState`, optional
        state of the LED, default is UNKNOWN

    Raises
    ------
    TypeError
        If channel provided is not valid.
    """

    def __init__(
        self,
        serial_number: str,
        channel: str,
        index: int = -1,
        status: LEDBasicState = LEDBasicState.UNKNOWN,
    ):
        self.serial = serial_number
        self.channel = channel
        self.index = index
        self.status = status

        # modbus channel dictionary
        self.offset_dict = {
            "AIN": 0,
            "DIO": 2000,
            "FIO": 2000,
            "EIO": 2008,
            "CIO": 2016,
            "MIO": 2020,
        }

        # protect against invalid entries
        if self.channel[:3] not in self.offset_dict or not self.channel[3:].isdigit():
            raise TypeError(f"Invalid labjack channel {self.channel}")

    def address(self) -> int:
        """Convert labjack channel name to their respective modbus address.

        Returns
        -------
        addNum : `int`
            Modbus address of the ljm channel.
        """
        addNum = int(self.channel[3:])

        # AIN are 32-bit wide, so their address takes up 2
        # addresses for the LSB/MSB
        if self.channel[:3] == "AIN":
            addNum *= 2
        else:
            # all other DIO is standard 16-bit wide transmission
            addNum += self.offset_dict[self.channel[:3]]
        return addNum

    def value(self, state_to_write: LEDBasicState) -> bool:
        """Wrapper to convert ON/OFF to the actual value to write

        Parameters
        ----------
        status : `LEDBasicState`
            State to set the LED to.
            Will only return 'ON' setting for ON, everything else will be OFF

        Returns
        -------
        state : `bool`
            Proper True/False to send to labjack
        """
        return False if state_to_write == LEDBasicState.ON else True


class LEDController(BaseLabJackDataClient):
    """Class to handle switching of LEDs connected to Labjack Interface

    Parameters
    ----------
    config : `types.SimpleNamespace`
        LED-specific configuration.
    log : `logging.Logger` or 'None', optional
        Logger.
    simulate : `bool`, optional
        Run in simulation mode?
    """

    def __init__(
        self,
        config: types.SimpleNamespace,
        log: logging.Logger | None = None,
        simulate: bool = False,
    ) -> None:
        super().__init__(
            config=config, topics=config.topics, log=log, simulation_mode=simulate
        )

        self.config = config
        self.log = (
            log.getChild(type(self).__name__)
            if log is not None
            else logging.getLogger(type(self).__name__)
        )

        # We want a multiple key -> 1 value list for easy parsing
        # We are creating a dictionary with 3 keys -> 1 value
        # 1st key : Serial number of the LED
        # 2nd key : 0-indexed list placement of the LED
        # 3rd key : Labjack Channel Name of that LED
        # First extract info from the config file,
        # note that were going to use the first
        # available 'ledControllerItem' in config,
        # as there should only be one anyway
        led_topic = next(
            topic
            for topic in self.config.topics
            if topic["topic_name"] == "ledControllerItem"
        )

        # Extract the serial and lbj channel name lists
        self.led_names = led_topic["led_names"]
        channel_names = led_topic["channel_names"]

        self.log.info(f"Opening led_controller with led names {self.led_names}")
        self.log.info(f"Opening led_controller with channel names {channel_names}")

        # combine the two lists into a list of tuples
        partial_key_tuple = list(zip(self.led_names, channel_names))

        # Now make a list of labjackchannel objs using the previous list's info
        # Note that we use enumerate to get the numerical index
        full_key_tuple = [
            LabjackChannel(serial_number=data[0], channel=data[1], index=ind)
            for ind, data in enumerate(partial_key_tuple, start=0)
        ]
        # Now create our multi-key dictionary
        self.channels: Dict[Union[str, int], LabjackChannel] = {}
        for lbc in full_key_tuple:
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
      additionalProperties: false
required:
  - device_type
  - connection_type
  - identifier
  - topics
additionalProperties: false
"""
        )

    async def run(self) -> None:
        """
        There is no use in constantly reading labjack status, so leave empty.
        common.BaseDataClient requires that we define it:
            TypeError: Can't instantiate abstract class
                        LEDController with abstract method run
        """
        pass

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
        if identifier in self.channels:
            return self.channels[identifier].status
        else:
            raise RuntimeError("Given identifier doesn't exist")

    def _set_state(self, identifier: str | int, status: LEDBasicState) -> None:
        """Set status.

        Parameters
        ----------
        identifier : `str` | `int`
            Serial number of LED or 0-indexed identifier
        status : `LEDBasicState`
            Status to set the LED to.

        Raises
        ------
        RuntimeError
            If identifier is not valid
        """
        # check that the identifier is valid
        # also check that the status has actually changed
        if identifier in self.channels:
            if self.channels[identifier].status is not status:
                self.channels[identifier].status = status
                self.log.info(f"LED {identifier} -> {status}")
            else:
                self.log.warning(f"LED {identifier} is already {status}")
        else:
            raise RuntimeError("Given identifier doesn't exist")

    async def switch_led(
        self,
        identifier: str | int,
        led_state: LEDBasicState,
    ) -> None:
        """Run a blocking function in a thread pool executor.

        Only one function will run at a time, because all calls use the same
        thread pool executor, which only has a single thread.

        Parameters
        ----------
        identifier : `str` | `int`
            The serial number of the LED, port of the labjack,
            or a 0-indexed identifier
        led_state : `LEDBasicState`
            ON to switch LED on, OFF to switch LED off

        Raises
        ------
        TypeError
            If the led_state given is invalid
        Exception
            If the blocking switch LED failed
        """
        loop = asyncio.get_running_loop()
        try:
            await asyncio.wait_for(
                loop.run_in_executor(
                    self._thread_pool,
                    functools.partial(
                        self._blocking_switch_led,
                        identifier=identifier,
                        led_state=led_state,
                    ),
                ),
                timeout=COMMUNICATION_TIMEOUT,
            )
        except asyncio.CancelledError:
            self.log.info(
                "run_in_thread cancelled while "
                f"running blocking function {self._blocking_switch_multiple_leds}."
            )
        except TypeError:
            self.log.exception("Invalid led_state to switch LED to")
            raise
        except Exception:
            self.log.exception(
                f"Blocking function {self._blocking_switch_multiple_leds} failed."
            )
            raise

    def _blocking_switch_led(
        self,
        identifier: str | int,
        led_state: LEDBasicState,
    ) -> None:
        """Switch the LED on/off.

        Parameters
        ----------
        identifier : `str` | `int`
            The serial number of the LED, port of the labjack,
            or a 0-indexed identifier
        led_state : `LEDBasicState`
            ON to switch LED on, OFF to switch LED off

        Raises
        ------
        RuntimeError
            If the Labjack cannot connect
            If the Labjack reports back an error
        TypeError
            If led_state is not ON or OFF
        """
        # Check that led_state is valid
        if led_state not in [LEDBasicState.ON, LEDBasicState.OFF]:
            raise TypeError("Invalid led_state to switch LED to")

        # Check we are not already in that state.
        if self.get_state(identifier) == led_state:
            self.log.warning(f"LED {identifier} is already {led_state}")
            return

        if self.handle is None:
            try:
                self.log.warning(
                    "Labjack not explicitly connected when calling switch_led,"
                    " attempting to connect now..."
                )
                self._blocking_connect()
            except RuntimeError:
                raise RuntimeError("Labjack unable to connect")

        # switch the LED.
        address = self.channels[identifier].address()
        value = self.channels[identifier].value(led_state)

        try:
            ljm.eWriteAddress(self.handle, address, ljm.constants.UINT16, value)
        except ljm.LJMError as ljm_error:
            # Set up log string
            error_code = ljm_error.errorCode
            error_string = str(ljm_error)
            log_string = str(
                f"Labjack reported error#{error_code} during eWriteAddress"
                f"in switch_led, dumping values: "
                f"identifier: {identifier} led_state: {led_state} "
                f"handle: {self.handle} address: {address} "
                f"data_type: {ljm.constants.UINT16} value_written: {value} "
                f"ljm_error_string: {error_string}"
            )

            # If error then raise except else its a warning so continue
            if error_code > ljm.errorcodes.WARNINGS_END:
                self.log.exception(log_string)
                raise RuntimeError(f"ljm reported error, see log: {log_string}")
            self.log.warning(log_string)

        # None of the warnings are egregious, so the state should have changed
        # Update state
        self._set_state(identifier, led_state)

    async def switch_all_leds_off(self) -> List[str]:
        """Switch ALL LEDs off"""
        await self.switch_multiple_leds(
            [led for led in self.channels],
            [LEDBasicState.OFF for _ in range(len(self.channels))],
        )
        return self.led_names

    async def switch_all_leds_on(self) -> List[str]:
        """Switch ALL LEDs on"""
        await self.switch_multiple_leds(
            [led for led in self.channels],
            [LEDBasicState.ON for _ in range(len(self.channels))],
        )
        return self.led_names

    async def switch_multiple_leds(
        self, identifiers: List[Union[str, int]], led_states: List[LEDBasicState]
    ) -> None:
        """Run a blocking function in a thread pool executor.

        Only one function will run at a time, because all calls use the same
        thread pool executor, which only has a single thread.

        Parameters
        ----------
        identifiers : `list of str or int`
            A list of serial numbers and/or 0-indexed identifiers
            of the LEDs to switch
        led_states : `list of LEDBasicState`
            A list of boolean states for the LEDs to be switched,
            true for on, false for off

        Raises
        ------
        Exception
            If the blocking switch multiple LEDs failed
        """
        loop = asyncio.get_running_loop()
        try:
            return await asyncio.wait_for(
                loop.run_in_executor(
                    self._thread_pool,
                    functools.partial(
                        self._blocking_switch_multiple_leds,
                        identifiers=identifiers,
                        led_states=led_states,
                    ),
                ),
                timeout=COMMUNICATION_TIMEOUT,
            )
        except asyncio.CancelledError:
            self.log.info(
                "run_in_thread cancelled while running "
                f"blocking function {self._blocking_switch_multiple_leds}."
            )
        except Exception:
            self.log.exception(
                f"Blocking function {self._blocking_switch_multiple_leds} failed."
            )
            raise

    def _blocking_switch_multiple_leds(
        self, identifiers: List[Union[str, int]], led_states: List[LEDBasicState]
    ) -> None:
        """Switch multiple LEDs at once.

        Parameters
        ----------
        identifiers : `list of str or int`
            A list of serial numbers and/or 0-indexed identifiers
            of the LEDs to switch
        led_states : `list of LEDBasicState`
            A list of boolean states for the LEDs to be switched,
            true for on, false for off

        Raises
        ------
        RuntimeError
            If the Labjack cannot connect
            If the len of identifiers & led_states is not equal.
            If the Labjack reports back an error
        TypeError
            If led_states includes an item that is not ON or OFF
        """
        # confirm that the lengths of both arrays match
        if len(identifiers) != len(led_states):
            self.log.error(
                f"Length of identifiers: {len(identifiers)}."
                f"Length of led_states: {len(led_states)}."
            )
            raise RuntimeError(
                "Length of identifiers and states in switch_multiple_leds doesn't match. "
                f"Got {len(identifiers)=} and {len(led_states)=}."
            )

        # confirm we have valid led_state values
        for state in led_states:
            if state not in [LEDBasicState.ON, LEDBasicState.OFF]:
                raise TypeError(f"{state} is an invalid state to set the LED to")

        # connect to labjack if we currently are disconnected
        if self.handle is None:
            try:
                self.log.info("Attempting to connect to Labjack...")
                self._blocking_connect()
            except RuntimeError:
                raise RuntimeError("Labjack can't connect")

        self.log.info(f"Switching LEDs {identifiers} to {led_states}")

        # form list of addresses and values to write
        addresses = [self.channels[identifier].address() for identifier in identifiers]
        values = [
            (self.channels[identifier].value(state))
            for state, identifier in zip(led_states, identifiers)
        ]
        try:
            ljm.eWriteAddresses(
                self.handle,
                len(identifiers),
                addresses,
                [ljm.constants.UINT16 for _ in led_states],
                values,
            )
        except ljm.LJMError as ljm_error:
            # Set up log string
            error_code = ljm_error.errorCode
            error_string = str(ljm_error)
            log_string = str(
                f"Labjack reported error#{error_code} during eWriteAddress"
                f"in switch_led, dumping values: "
                f"identifiers: {identifiers} led_states: {led_states} "
                f"handle: {self.handle} addresses: {addresses} "
                f"data_type: {ljm.constants.UINT16} values_written: {values} "
                f"ljm_error_string: {error_string}"
            )

            # If error then raise except else its a warning so continue
            if error_code > ljm.errorcodes.WARNINGS_END:
                self.log.exception(log_string)
                raise RuntimeError(f"ljm reported error, see log: {log_string}")
            self.log.warning(log_string)

        # Update state
        for count, identifier in enumerate(identifiers, start=0):
            self._set_state(identifier, led_states[count])

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
        self.log.info("Attempting to connect to Labjack...")
        super()._blocking_connect()

        # Configure flexible IO to digital
        # The DIO_INHIBIT hex is what qualifies something as being digital.
        # 0 bit = digital. Read from LSB, ex: FIO0 is bit 0
        self.log.info("Setting all IO as DIO...")
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
