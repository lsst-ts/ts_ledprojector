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

__all__ = ["CONFIG_SCHEMA"]

import yaml

# $schema: http://json-schema.org/draft-07/schema#
# $id: https://github.com/lsst-ts/
# ts_ledprojector/python/lsst/ts/ledprojector/config_schema.py
CONFIG_SCHEMA = yaml.safe_load(
    """
schema: http://json-schema.org/draft-07/schema#
title: LEDProjector v2
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
        dac_mapping:
            description: >-
                LabJack DAC mapping to the LED channel names, in order of the field array.
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
        - dac_mapping
      additionalProperties: false
required:
  - device_type
  - connection_type
  - identifier
  - topics
additionalProperties: false
"""
)
