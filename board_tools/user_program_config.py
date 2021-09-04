#__________Main user program configs__________:
DEBUG = False

def debug_print(text):
    if DEBUG:
        print(text)

MENU_OPTIONS = [
    "Refresh",
    "Connect",
    "Configure",
    "Log",
    "Monitor",
    "NTRIP",
    "Upgrade",
    #"Plot", # put this back in menu when implemented
    "Exit"
]

# Error codes - should only get error 8 when using config.py
ERROR_CODES = {
    1: "No start character",
    2: "Missing r/w for config",
    3: "Incomplete Message",
    4: "Invalid Checksum",
    5: "Invalid Talker code",
    6: "Invalid Message Type",
    7: "Invalid Field",
    8: "Invalid Value",
    9: "Flash Locked",
    10: "Unexpected Character",
    11: "Feature Disabled"
}

CFG_FIELD_NAMES = [
    "OUTPUT DATA RATE",
    "ORIENTATION",
    "ENABLE GPS",
    #"GPS 2",
    "ODOMETER",
    "ENABLE FOG",
    "DHCP (AUTO ASSIGN IP)",
    "UDP A-1 IP",
    "UDP COMPUTER IP",
    "UDP COMPUTER DATA PORT ",
    "UDP COMPUTER CONFIGURATION PORT"
]

# cfg codes in messaging. must match order of CFG_FIELD_NAMES
# TODO use a dict or 2-way lookup?
CFG_FIELD_CODES = [
    "odr",
    "orn",
    "gps1",
    #"gps2",
    "odo",
    "fog",
    "dhcp",
    "lip",
    "rip",
    "rport1",
    "rport2"
]

#UDP_FIELD_INDICES = [5, 6, 7, 8, 9]  # udp related field positions in CFG_FIELD_NAMES / CODES
UDP_FIELDS = ["dhcp","lip", "rip", "rport1", "rport2"]

# suggestions on what you can enter. only for type in options
CFG_FIELD_EXAMPLES = {
    "orn": "(e.g. +X-Y-Z or any of the possible 24 right-handed frame options)",
    "lip": "(aaa.bbb.ccc.ddd)",
    "rip": "(aaa.bbb.ccc.ddd)",
    "rport1": "(int from 1 to 65535)",
    "rport2": "(int from 1 to 65535)"
}

# fixed list of values to select
CFG_VALUE_OPTIONS = {
    "orn": ["North-East-Down (+X+Y+Z)", "East-North-Up (+Y+X-Z)", "Select Other"],
    "odr": [20, 50, 100, 200],
    "gps1": ["on", "off"],
    #"gps2": ["on", "off"],
    "odo": ["mps", "mph", "kph", "fps"],
    "fog": ["on", "off"],
    "dhcp": ["on", "off"]
}

#UDP constants
#A1_port1 = UDP_LOCAL_DATA_PORT
#A1_port2 = UDP_LOCAL_CONFIG_PORT
UDP_CACHE = "udp_settings.txt"
NTRIP_CACHE = "ntrip_settings.txt"


CONNECT_RETRIES=3
RUNNING_RETRIES=10
FLUSH_FREQUENCY = 200

#__________Log export configs__________:
EXPORT_MESSAGE_TYPES = [b'IMU', b'INS', b'GPS']
EXPORT_IMU_FIELDS = ["imu_time_ms","accel_x_g","accel_y_g","accel_z_g",
                     "angrate_x_dps","angrate_y_dps","angrate_z_dps","fog_angrate_dps",
                     "odometer_speed_mps","odometer_time_ms","temperature_c"]

EXPORT_GPS_FIELDS = ["imu_time_ms","gps_time_ns","lat_deg","lon_deg","alt_ellipsoid_m","alt_msl_m",
                    "speed_mps","heading_deg","accuracy_horizontal_m","accuracy_vertical_m","PDOP",
                    "gnss_fix_type","num_sats","speed_accuracy_mps", "heading_accuracy_deg","carrier_solution_status", "position_geojson"]

EXPORT_INS_FIELDS = ["imu_time_ms","gps_time_ns","ins_solution_status","lat_deg","lon_deg","alt_m",
                    "velocity_0_mps","velocity_1_mps","velocity_2_mps","attitude_0_deg", "attitude_1_deg","attitude_2_deg",
                     "zupt_flag", "position_geojson"]

EXPORT_DEFAULT_COLOR = [200,200,200]

EXPORT_GPS_RADIUS = 3
EXPORT_GPS_COLOR_BASED_ON = "carrier_solution_status"
EXPORT_GPS_COLORS = {0:[255, 0, 0], 1:[255, 255, 0], 2:[0, 255, 0]}

EXPORT_INS_RADIUS = 1
EXPORT_INS_COLOR_BASED_ON = "zupt_flag"
EXPORT_INS_COLORS = {0: [0, 255, 0], 1: [255, 0, 0]}

#__________monitor configs__________:
MONITOR_REFRESH_MS = 100 #100
MONITOR_DEFAULT_VALUE = "--------------"
ZERO_OUT_TIME = 5
SGTHEME = "darkblue"
# BASE_WIDTH = 1124
# BASE_HEIGHT = 554
MONITOR_LATLON_SIZE = (12,1)
MONITOR_VALUE_SIZE = (10, 1)
FONT_NAME = "arial"
VALUE_FONT_SIZE = 40
MONITOR_LABEL_SIZE = (15,1)
LABEL_FONT_SIZE = 12
GPS_TEXT = "GPS: "
LOG_TEXT = "LOG: "
TOGGLE_TEXT = {True:"on", False: "off"}
TOGGLE_COLORS = {True: "green", False: "red"}
BUTTON_DISABLE_COLOR = "gray"
GPS_SOLN_NAMES = {0: "No solution", 1: "Float", 2: "Fix"}
GPS_FIX_NAMES = {0: "no fix",
                 1: "dead reckoning only",
                 2: "2D-fix",
                 3: "3D-fix",
                 4: "GNSS + dead reckoning combined",
                 5: "time only fix" } #from nav-pvt fix-type: see https://www.u-blox.com/en/docs/UBX-18010854
INS_SOLN_NAMES = {0: "attitude", 1: "position", 2: "heading", 3: "RTK float", 4: "RTK fix"} #TODO check these too
ZUPT_NAMES = {0: "moving", 1: "stationary"}
