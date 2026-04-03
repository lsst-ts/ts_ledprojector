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

import pathlib
import unittest
from typing import Any, Callable
from unittest import mock

from lsst.ts import ledprojector, salobj
from lsst.ts.ledprojector import LEDProjectorCsc
from lsst.ts.xml.enums.LEDProjector import LEDBasicState

TEST_CONFIG_DIR = pathlib.Path(__file__).parents[1].joinpath("tests", "data", "config")
SHORT_TIMEOUT = 5
MEAS_TIMEOUT = 10


class CscTestCase(salobj.BaseCscTestCase, unittest.IsolatedAsyncioTestCase):
    def basic_make_csc(
        self, initial_state: int, config_dir: str, simulation_mode: int, **kwargs: Any
    ) -> LEDProjectorCsc:
        return ledprojector.LEDProjectorCsc(
            initial_state=initial_state,
            config_dir=config_dir,
            simulation_mode=simulation_mode,
        )

    async def test_standard_state_transitions(self) -> None:
        async with self.make_csc(
            initial_state=salobj.State.STANDBY,
            config_dir=TEST_CONFIG_DIR,
            simulation_mode=1,
        ):
            await self.check_standard_state_transitions(
                enabled_commands=(
                    "switchAllOn",
                    "switchAllOff",
                    "switchOn",
                    "switchOff",
                    "adjustAllDACPower",
                    "adjustDACPower",
                ),
            )

    async def test_version(self) -> None:
        async with self.make_csc(
            initial_state=salobj.State.STANDBY,
            config_dir=TEST_CONFIG_DIR,
            simulation_mode=1,
        ):
            await self.assert_next_sample(
                self.remote.evt_softwareVersions,
                cscVersion=ledprojector.__version__,
                subsystemVersions="",
            )

    async def test_bin_script(self) -> None:
        await self.check_bin_script(name="LEDProjector", index=0, exe_name="run_ledprojector")

    async def test_fault(self) -> None:
        async with self.make_csc(
            initial_state=salobj.State.ENABLED, config_dir=TEST_CONFIG_DIR, simulation_mode=1
        ):
            await self.assert_next_summary_state(salobj.State.ENABLED, timeout=SHORT_TIMEOUT)
            await self.assert_next_sample(self.remote.evt_errorCode, errorCode=0)
            assert self.csc.led_controller is not None
            self.csc.led_controller.handle = None
            await self.assert_next_summary_state(salobj.State.FAULT, timeout=SHORT_TIMEOUT)
            await self.assert_next_sample(self.remote.evt_errorCode, errorCode=2)

    async def test_switch_leds(self) -> None:
        async with self.make_csc(
            initial_state=salobj.State.ENABLED,
            config_dir=TEST_CONFIG_DIR,
            simulation_mode=1,
        ):
            # TODO DM-44713 Remove when XML v21 is released.
            try:
                self.remote.cmd_switchOn.set(serialNumbers="M375L4")
            except AttributeError:
                self.remote.cmd_switchOn.set(serialNumber="M375L4")

            await self.remote.cmd_switchOn.start(timeout=SHORT_TIMEOUT)

            led_state = await self.assert_next_sample(
                topic=self.remote.evt_ledState,
            )
            assert led_state.serialNumber == "M375L4"
            assert led_state.ledBasicState == LEDBasicState.ON

            # TODO DM-44713 Remove when XML v21 is released.
            try:
                value = led_state.value
                assert value == 0
            except AttributeError:
                pass

            # TODO DM-44713 Remove when XML v21 is released.
            try:
                self.remote.cmd_switchOff.set(serialNumbers="M375L4")
            except AttributeError:
                self.remote.cmd_switchOff.set(serialNumber="M375L4")

            await self.remote.cmd_switchOff.start(timeout=SHORT_TIMEOUT)

            led_state = await self.assert_next_sample(
                topic=self.remote.evt_ledState,
                serialNumber="M375L4",
                ledBasicState=LEDBasicState.OFF,
            )
            # TODO DM-44713 Remove when XML v21 is released.
            try:
                value = led_state.value
                assert value == 0
            except AttributeError:
                pass

    async def test_enable_retries_controller_connection(self) -> None:
        open_attempts = 0

        class FakeLJMError(Exception):
            def __init__(self, error_code: int, error_string: str) -> None:
                super().__init__(error_string)
                self.errorCode = error_code
                self.errorString = error_string

        async def run_side_effect(func: Callable, *args: Any, **kwargs: Any) -> None | str | list[int]:
            nonlocal open_attempts

            if func is ledprojector.led_controller.ljm.open:
                open_attempts += 1
                if open_attempts < 3:
                    raise FakeLJMError(1234, "temporary open failure")
                return "connected-handle"

            if func is ledprojector.led_controller.ljm.eReadNames:
                return [0] * args[1]

            return None

        with (
            mock.patch.object(ledprojector.led_controller, "COMMUNICATION_TIMEOUT", 0),
            mock.patch.object(ledprojector.ledprojector_csc, "COMMUNICATION_TIMEOUT", SHORT_TIMEOUT),
            mock.patch.object(ledprojector.led_controller.ljm, "LJMError", FakeLJMError),
            mock.patch.object(
                ledprojector.led_controller.LEDController,
                "run",
                new=mock.AsyncMock(side_effect=run_side_effect),
            ) as run_mock,
        ):
            async with self.make_csc(
                initial_state=salobj.State.ENABLED,
                config_dir=TEST_CONFIG_DIR,
                simulation_mode=1,
            ):
                assert self.csc.summary_state == salobj.State.ENABLED
                assert self.csc.led_controller is not None
                assert self.csc.led_controller.handle == "connected-handle"

        assert open_attempts == 3
        open_calls = [
            call
            for call in run_mock.await_args_list
            if call.args and call.args[0] is ledprojector.led_controller.ljm.open
        ]
        assert len(open_calls) == 3

    async def test_switch_on_reconnects_controller(self) -> None:
        async with self.make_csc(
            initial_state=salobj.State.ENABLED,
            config_dir=TEST_CONFIG_DIR,
            simulation_mode=1,
        ):
            assert self.csc.led_controller is not None
            self.csc.heartbeat_interval = 60
            self.csc.led_controller.handle = None

            async def connect_side_effect() -> None:
                assert self.csc.led_controller is not None
                self.csc.led_controller.handle = "reconnected-handle"

            self.csc.led_controller.connect = mock.AsyncMock(side_effect=connect_side_effect)
            self.csc.led_controller.run = mock.AsyncMock(return_value=None)

            try:
                self.remote.cmd_switchOn.set(serialNumbers="M375L4")
            except AttributeError:
                self.remote.cmd_switchOn.set(serialNumber="M375L4")

            await self.remote.cmd_switchOn.start(timeout=SHORT_TIMEOUT)

            self.csc.led_controller.connect.assert_awaited_once()
            self.csc.led_controller.run.assert_awaited_once_with(
                ledprojector.led_controller.ljm.eWriteAddresses,
                "reconnected-handle",
                1,
                [self.csc.led_controller.channels["M375L4"].address()],
                [ledprojector.led_controller.ljm.constants.UINT16],
                [False],
            )

            led_state = await self.assert_next_sample(
                topic=self.remote.evt_ledState,
                serialNumber="M375L4",
                ledBasicState=LEDBasicState.ON,
            )
            assert led_state.serialNumber == "M375L4"
