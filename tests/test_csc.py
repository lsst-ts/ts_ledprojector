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
from typing import Any

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
        await self.check_bin_script(
            name="LEDProjector", index=0, exe_name="run_ledprojector"
        )

    async def test_switch_leds(self) -> None:
        async with self.make_csc(
            initial_state=salobj.State.ENABLED,
            config_dir=TEST_CONFIG_DIR,
            simulation_mode=1,
        ):
            await self.remote.cmd_switchOn.set_start(
                serialNumbers="M375L4", timeout=SHORT_TIMEOUT
            )

            await self.assert_next_sample(
                topic=self.remote.evt_ledState,
                serialNumber="M375L4",
                ledBasicState=LEDBasicState.ON,
                value=0,
            )

            await self.remote.cmd_switchOff.set_start(
                serialNumbers="M375L4", timeout=SHORT_TIMEOUT
            )

            await self.assert_next_sample(
                topic=self.remote.evt_ledState,
                serialNumber="M375L4",
                ledBasicState=LEDBasicState.OFF,
                value=0,
            )
