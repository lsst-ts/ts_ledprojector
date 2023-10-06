"""Sphinx configuration file for an LSST stack package.

This configuration only affects single-package Sphinx documentation builds.
For more information, see:
https://developer.lsst.io/stack/building-single-package-docs.html
"""

import lsst.ts.ledprojector  # noqa
from documenteer.conf.pipelinespkg import *  # type: ignore # noqa

project = "ts_ledprojector"
html_theme_options["logotext"] = project  # type: ignore # noqa
html_title = project
html_short_title = project

intersphinx_mapping["ts_ess_common"] = ("https://ts-ess-common.lsst.io", None)  # type: ignore # noqa
intersphinx_mapping["ts_salobj"] = ("https://ts-salobj.lsst.io", None)  # type: ignore # noqa
intersphinx_mapping["ts_utils"] = ("https://ts-utils.lsst.io", None)  # type: ignore # noqa
intersphinx_mapping["ts_ess_labjack"] = ("https://ts-ess-labjack.lsst.io", None)  # type: ignore # noqa
