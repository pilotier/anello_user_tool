READABLE_START = b'#'
READABLE_END = b'\r\n'
READABLE_TALKER_LENGTH = 2
READABLE_TYPE_LENGTH = 3
READABLE_CHECKSUM_SEPARATOR = b'*'
READABLE_PAYLOAD_SEPARATOR = b','
OUR_TALKER = b'AP'

#for CFG type
WRITE_RAM = b'w'
READ_RAM = b'r'
WRITE_FLASH = b'W'
READ_FLASH = b'R'

#time as float # of ms, accel_x, accel_y, accel_z, rate_x, rate_y, rate_z, temperature with no counter
#ex: GPCAL,71822.885,102,-103,4165,46,29,-6,1955*4C
FORMAT_CAL = [
    ("time", float),
    ("accel_x", int),
    ("accel_y", int),
    ("accel_z", int),
    ("rate_x", int),
    ("rate_y", int),
    ("rate_z", int),
    ("temperature", int)
]

#APIMU,7757199.318,-0.0004,0.0131,0.5096,1.8946,-0.2313,-0.4396,0*7E
FORMAT_IMU = [
    ("time", float),
    ("accel_x", float),
    ("accel_y", float),
    ("accel_z", float),
    ("rate_x", float),
    ("rate_y", float),
    ("rate_z", float),
    ("fog_volts", float),
    ("fog_rate", float),
    ("odometer_speed", float),
    ("odometer_time", float),
    ("temperature", float)
]

FORMAT_VER = [
    ('ver', bytes)
]

FORMAT_SER = [
    ('ser', bytes)
]

FORMAT_PID = [
    ('pid', bytes)
]

# Error message has error code - int indicating which kind of error
FORMAT_ERR = [
    ('err', int)
]
ERROR_NO_START = 1
ERROR_NO_READ_WRITE = 2
ERROR_INCOMPLETE = 3
ERROR_CHECKSUM = 4
ERROR_TALKER = 5
ERROR_MSG_TYPE = 6
ERROR_FIELD = 7
ERROR_VALUE = 8
ERROR_FLASH_LOCKED = 9
ERROR_UNEXPECTED_CHAR = 10
ERROR_FEATURE_DISABLED = 11

# temporary status format: APSTA,errs,0,warnings,0,overall,PEACHY!*10
FORMAT_STA = [
    ("errs", int),
    ("warnings", int),
    ("overall", bytes)
]

# Reset has a code for reset type: 0-processor, 1-algorithm

FORMAT_RST = [
    ("code", int)
]

# ping response has a single number, constant
FORMAT_PNG = [
    ("code", int)
]

#APGPS elements (derived from ublox NAV-PVT message):
#APGPS,50057648,320315000.000,37.3990838,-121.9791725,-28.0670,1.8220,0.0360,232.6868,5.8751,5.8751,1.2600,3,20*72

# payload:                      ex value
    # imu time [msec]           50057648
    # gps (ITOW) time [msec]    320315000.000
    # lat [deg]                 37.3990838
    # lon [deg]                 -121.9791725
    # alt above ellipsoid [m]   -28.0670
    # alt above MSL [m]         1.8220
    # speed [m/s]               0.0360
    # heading [deg]             232.6868
    # Accur meas [m]            5.8751
    # Accur meas [m]            5.8751
    # PDOP                      1.2600
    # fix-type                  3
    # number of satellites      20

FORMAT_GPS = [
    ("imu_time_ms", int),
    ("gps_time_ms", float),
    ("lat", float),
    ("lon", float),
    ("alt_ellipsoid_m", float),
    ("alt_msl_m", float),
    ("speed_m_per_s", float),
    ("heading_degrees", float),
    ("acc_horizontal_m", float),
    ("acc_vertical_m", float),
    ("PDOP", float),
    ("fix-type", int),
    ("numSV", int),
    ("spdacc", float),
    ("hdsacc", float)
]

FORMAT_ODO = [
    ("speed", float)
]

