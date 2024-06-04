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

import asyncio
import contextlib
import logging
import pathlib
import random
import types
import unittest
from collections.abc import AsyncGenerator
from typing import TypeAlias

import yaml
from jsonschema.exceptions import ValidationError
from lsst.ts import ledprojector, salobj
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
        assert len(topic) == 6
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

        assert len(topic["dac_mapping"]) == len(topic["led_names"])
        await self.valid_list(
            validList=["DAC0", "DAC0", "DAC1", "DAC1"], listToTest=topic["dac_mapping"]
        )

    async def test_state_change(self) -> None:
        config = self.get_config("config.yaml")
        led_client = ledprojector.LEDController(
            config=config,
            log=self.log,
            simulate=True,
        )

        # status should be unknown on creation
        for channel in set(led_client.channels.values()):
            assert channel.status is LEDBasicState.UNKNOWN

        # make sure it asserts if we give it invalid identifier
        with self.assertRaises(RuntimeError):
            led_client._set_state("bogus", LEDBasicState.ON)
            led_client.get_state("bogus")
            led_client.get_state(len(config.topics[0]["channel_names"] + 1))

        # accept proper values and go by multiple identifiers
        led_client._set_state("DIO1", LEDBasicState.ON)
        assert led_client.get_state("DIO1") is LEDBasicState.ON
        assert led_client.get_state("M375L4") is LEDBasicState.ON
        assert led_client.get_state(0) is LEDBasicState.ON

        led_client._set_state("M375L4", LEDBasicState.OFF)
        assert led_client.get_state("DIO1") is LEDBasicState.OFF

    async def test_connecting(self) -> None:
        config = self.get_config("config.yaml")
        led_client = ledprojector.LEDController(
            config=config,
            log=self.log,
            simulate=True,
        )

        # test connection and disconnection
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
            assert channel.status is LEDBasicState.UNKNOWN

        # confirm that we cannot switch led to state that isn't on/off
        for state in LEDBasicState:
            if state not in [LEDBasicState.ON, LEDBasicState.OFF]:
                with self.assertRaises(TypeError):
                    await asyncio.wait_for(
                        led_client.switch_multiple_leds(["M375L4"], [state]), timeout=5
                    )

        # accept proper values and go by multiple identifiers
        await asyncio.wait_for(
            led_client.switch_multiple_leds(["M375L4"], [LEDBasicState.ON]), timeout=5
        )
        assert led_client.get_state("DIO1") is LEDBasicState.ON
        assert led_client.get_state("M375L4") is LEDBasicState.ON
        assert led_client.get_state(0) is LEDBasicState.ON

        await led_client.switch_multiple_leds(["CIO3"], [LEDBasicState.OFF])
        assert led_client.get_state("CIO3") is LEDBasicState.OFF
        assert led_client.get_state("M505L4") is LEDBasicState.OFF
        assert led_client.get_state(2) is LEDBasicState.OFF

    async def test_multiple_led_switching(self) -> None:
        config = self.get_config("config.yaml")
        led_client = ledprojector.LEDController(
            config=config,
            log=self.log,
            simulate=True,
        )
        # test multiples
        await led_client.switch_multiple_leds(
            ["M375L4", "EIO3", "M505L4", 1], [LEDBasicState.ON for i in range(4)]
        )

        # confirm the states
        topic = config.topics[0]
        for channel in topic["led_names"]:
            assert led_client.get_state(channel) is LEDBasicState.ON
        for channel in topic["channel_names"]:
            assert led_client.get_state(channel) is LEDBasicState.ON
        for i in range(4):
            assert led_client.get_state(i) is LEDBasicState.ON

        # test length of identifier/state mismatch
        with self.assertRaises(RuntimeError):
            await asyncio.wait_for(
                led_client.switch_multiple_leds(
                    ["M375L4", "EIO3"], [LEDBasicState.ON for i in range(3)]
                ),
                timeout=5,
            )

        # test invalid states on multiple led switch
        for state in LEDBasicState:
            if state not in [LEDBasicState.ON, LEDBasicState.OFF]:
                with self.assertRaises(TypeError):
                    await asyncio.wait_for(
                        led_client.switch_multiple_leds(
                            ["M375L4", "EIO3"], [state for i in range(2)]
                        ),
                        timeout=5,
                    )

    async def test_switch_all_off(self) -> None:
        config = self.get_config("config.yaml")
        led_client = ledprojector.LEDController(
            config=config,
            log=self.log,
            simulate=True,
        )
        topic = config.topics[0]
        for channel in topic["led_names"]:
            await asyncio.wait_for(
                led_client.switch_multiple_leds(
                    [channel],
                    [LEDBasicState.ON if random.randrange(2) else LEDBasicState.OFF],
                ),
                timeout=5,
            )
        await led_client.switch_all_leds_off()

        for channel in set(led_client.channels.values()):
            assert channel.status is LEDBasicState.OFF

    async def test_switch_all_on(self) -> None:
        config = self.get_config("config.yaml")
        led_client = ledprojector.LEDController(
            config=config,
            log=self.log,
            simulate=True,
        )
        topic = config.topics[0]
        for channel in topic["led_names"]:
            await asyncio.wait_for(
                led_client.switch_multiple_leds(
                    [channel],
                    [LEDBasicState.ON if random.randrange(2) else LEDBasicState.OFF],
                ),
                timeout=5,
            )
        await led_client.switch_all_leds_on()

        for channel in set(led_client.channels.values()):
            assert channel.status is LEDBasicState.ON

    async def test_adjust_dac_value(self) -> None:
        config = self.get_config("config.yaml")
        led_client = ledprojector.LEDController(
            config=config,
            log=self.log,
            simulate=True,
        )
        # turn all leds on
        await led_client.switch_all_leds_on()

        for channel in set(led_client.channels.values()):
            assert channel.status is LEDBasicState.ON

        # test good values
        topic = config.topics[0]
        print("\nTEST!: " + str(topic["led_names"]))
        for channel in topic["led_names"]:
            await asyncio.wait_for(
                led_client.adjust_dac_values(
                    [channel],
                    [random.randrange(0, 5)],
                ),
                timeout=5,
            )

        # test bad values
        with self.assertRaises(ValueError):
            await asyncio.wait_for(
                led_client.adjust_dac_values(["CIO3"], [6000]),
                timeout=5,
            )

        with self.assertRaises(ValueError):
            await asyncio.wait_for(
                led_client.adjust_dac_values(
                    ["ASDF"],
                    [3],
                ),
                timeout=5,
            )

        # test multiple
        await asyncio.wait_for(
            led_client.adjust_dac_values(
                topic["led_names"][:-2],
                [random.randrange(0, 5)],
            ),
            timeout=5,
        )

        # test all
        await asyncio.wait_for(
            led_client.adjust_all_dac_values(
                value=random.randrange(0, 5),
            ),
            timeout=5,
        )

    async def test_bad_configs(self) -> None:
        # test various bad yamls, missing required values
        for i in range(8):
            with self.assertRaises(ValidationError):
                self.get_config(f"bad_config{i}.yaml")

    async def test_minimal(self) -> None:
        # test minimal yaml (missing values where default is set)
        self.get_config("good_minimal.yaml")

    async def test_labjack_channel_class(self) -> None:
        bad_channels = {"AIN", "AINO1"}

        for chan in bad_channels:
            with self.assertRaises(TypeError):
                ledprojector.led_controller.LabjackChannel(
                    serial_number="ASDF", channel=chan
                )

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
