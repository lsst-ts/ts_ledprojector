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

import contextlib
import logging
import pathlib
import types
import unittest
from collections.abc import AsyncGenerator
from typing import TypeAlias

import yaml
from lsst.ts import ledprojector, salobj
from lsst.ts.ess import common, labjack
from lsst.ts.xml.enums.LEDProjector import LEDBasicState

logging.basicConfig(
    format="%(asctime)s:%(levelname)s:%(name)s:%(message)s", level=logging.DEBUG
)

PathT: TypeAlias = str | pathlib.Path

# Standard timeout in seconds
TIMEOUT = 5


class DataClientTestCase(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.log = logging.getLogger()
        self.data_dir = pathlib.Path(__file__).parent / "data" / "config"

        config_schema = ledprojector.LEDController.get_config_schema()
        self.validator = salobj.DefaultingValidator(config_schema)

    @contextlib.asynccontextmanager
    async def make_topics(self) -> AsyncGenerator[types.SimpleNamespace, None]:
        salobj.set_random_lsst_dds_partition_prefix()
        async with salobj.make_mock_write_topics(
            name="ESS", attr_names=["ledController"]
        ) as topics:
            yield topics

    async def valid_list(self, validList: list[str], listToTest: list[str]) -> None:
        for item in listToTest:
            if item not in validList:
                assert False

    async def test_constructor_good_full(self) -> None:
        """Construct with good_full.yaml and compare values to that file.

        Use the default simulation_mode.
        """
        config = self.get_config("config.yaml")
        led_client = ledprojector.LEDController(
            config=config,
            log=self.log,
            simulate=True,
        )
        assert led_client.simulation_mode == 1
        assert isinstance(led_client.log, logging.Logger)
        topic = config.topics[0]
        assert len(topic) == 5
        assert len(topic["channel_names"]) == 4
        await self.valid_list(
            validList=["DIO1", "FIO0", "CIO3", "EIO3"],
            listToTest=topic["channel_names"],
        )

        assert len(config.topics) == 1
        assert topic["topic_name"] == "ledControllerItem"
        assert topic["sensor_name"] == "labjack_test_1"
        assert topic["location"] == "somewhere, nowhere, somewhere else, guess"
        assert len(topic["led_names"]) == 4

        await self.valid_list(
            validList=["M375L4", "M445L4", "M505L4", "M565L4"],
            listToTest=topic["led_names"],
        )

    async def test_registry(self) -> None:
        data_client_class = common.get_data_client_class("LabJackDataClient")
        assert data_client_class is labjack.LabJackDataClient

    async def test_state_change(self) -> None:
        config = self.get_config("config.yaml")
        led_client = ledprojector.LEDController(
            config=config,
            log=self.log,
            simulate=True,
        )

        # status should be unknown on creation
        for channel in set(led_client.channels.values()):
            assert channel.status == LEDBasicState.UNKNOWN

        # make sure it asserts if we give it invalid identifier
        with self.assertRaises(RuntimeError):
            await led_client.set_state("bogus", LEDBasicState.ON)
            led_client.get_state("bogus")
            led_client.get_state(len(config.topics[0]["channel_names"] + 1))

        # accept proper values and go by multiple identifiers
        await led_client.set_state("DIO1", LEDBasicState.ON)
        assert led_client.get_state("DIO1") == LEDBasicState.ON
        assert led_client.get_state("M375L4") == LEDBasicState.ON
        assert led_client.get_state(0) == LEDBasicState.ON

        await led_client.set_state("M375L4", LEDBasicState.OFF)
        assert led_client.get_state("DIO1") == LEDBasicState.OFF

    async def test_connecting(self) -> None:
        config = self.get_config("config.yaml")
        led_client = ledprojector.LEDController(
            config=config,
            log=self.log,
            simulate=True,
        )

        # test connection and disconnection
        # TODO: am I able to test when there are a mismatch of sensors given
        # vs whats already on the labjack? as asserted by RuntimeError
        await led_client.connect()
        await led_client.disconnect()

    async def test_led_switching(self) -> None:
        config = self.get_config("config.yaml")
        led_client = ledprojector.LEDController(
            config=config,
            log=self.log,
            simulate=True,
        )

        # status should be unknown on creation
        for channel in set(led_client.channels.values()):
            assert channel.status == LEDBasicState.UNKNOWN

        await led_client.switch_led("M375L4", LEDBasicState.ON)
        assert led_client.get_state("DIO1") == LEDBasicState.ON
        assert led_client.get_state("M375L4") == LEDBasicState.ON
        assert led_client.get_state(0) == LEDBasicState.ON

        # accept proper values and go by multiple identifiers
        await led_client.switch_led("CIO3", LEDBasicState.OFF)
        assert led_client.get_state("CIO3") == LEDBasicState.OFF
        assert led_client.get_state("M505L4") == LEDBasicState.OFF
        assert led_client.get_state(2) == LEDBasicState.OFF

        await led_client.switch_multiple_leds(
            ["M375L4", "EIO3", "M505L4", 1], [LEDBasicState.ON for i in range(4)]
        )

        topic = config.topics[0]
        for channel in topic["led_names"]:
            assert led_client.get_state(channel) == LEDBasicState.ON
        for channel in topic["channel_names"]:
            assert led_client.get_state(channel) == LEDBasicState.ON
        for i in range(4):
            assert led_client.get_state(i) == LEDBasicState.ON

    def get_config(self, filename: PathT) -> types.SimpleNamespace:
        """Get a config dict from tests/data.

        This should always be a good config,
        because validation is done by the ESS CSC,
        not the data client.

        Parameters
        ----------
        filename : `str` or `pathlib.Path`
            Name of config file, including ".yaml" suffix.

        Returns
        -------
        config : types.SimpleNamespace
            The config dict.
        """
        with open(self.data_dir / filename, "r") as f:
            raw_config_dict = yaml.safe_load(f.read())
        config_dict = self.validator.validate(raw_config_dict)
        return types.SimpleNamespace(**config_dict)
