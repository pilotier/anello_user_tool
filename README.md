This repo contains tools for connecting to and configuring the A-1 unit.

- contents:
    - config.py  - interactive configuration tool. Can set and read the user and factory settings.
        - usage: python config.py
    - bringup.py - tool to put standard configurations on a new IMU. Takes serial number as command line argument
        - usage: python bringup.py <serial num>
    - calibration -  methods to calibrate acceleration and rate sensors - not complete
    - test directory-  tests for IMU messaging using pytest. Some tests require GPS to be attached or other things.
        - run tests: pytest
        - show detailed results: pytest -v
        - run a subset of tests: pytest -k <name>
            - where <name> is a test function, file or directory.
    - test/timing.py - example application to plot data from the board
        - usage: python test/timing.py
    - src/tools - library for communicating with the IMU, used by the other parts

- requirements:
    - Python 3
    - python libraries: install with "pip install -r requirements.txt"
        - matplotlib
        - pynmea2
        - pandas
        - pyserial
        - cutie
        - numpy
        - pytest
        - Cython
