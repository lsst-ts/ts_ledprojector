v0.3.0 (2026-07-15)
===================

New Features
------------

- Added functionality to look up IP address by host name before creating Labjack connection. (`OSW-1855 <https://rubinobs.atlassian.net//browse/OSW-1855>`_)
- Added publishing of the ``ledsOn`` event with comma-delimited LED serial numbers and DAC values for LEDs that are currently on. (`OSW-2379 <https://rubinobs.atlassian.net//browse/OSW-2379>`_)


Performance Enhancement
-----------------------

- Improved reconnection handling. (`OSW-2109 <https://rubinobs.atlassian.net//browse/OSW-2109>`_)


v0.2.1 (2026-01-22)
===================

Performance Enhancement
-----------------------

- Added reconnection attempts when writing to labjack. (`OSW-698 <https://rubinobs.atlassian.net//browse/OSW-698>`_)


Other Changes and Additions
---------------------------

- Added build string to differeniate between python versions. (`OSW-1484 <https://rubinobs.atlassian.net//browse/OSW-1484>`_)


.. py:currentmodule:: lsst.ts.ledprojector

.. _lsst.ts.version_history:

###############
Version History
###############

v0.1.0
------

* The first release.
