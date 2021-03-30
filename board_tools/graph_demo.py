# import pytest
# import time
# import matplotlib.pyplot as plt

# import tools package by path relative to this file
import sys
import pathlib
parent_dir = str(pathlib.Path(__file__).parent)
sys.path.append(parent_dir+'/src')
from tools import *

#___________________CONFIG SECTION:_________________________
# these numbers should work well with any combination of booleans

#udp settings
connect_udp = False  # if false, connects by COM
A1_ip = "10.1.10.98"
udp_computer_ip = "10.1.10.48"
computer_port1 = 1111
computer_port2 = 2222
#end udp settings

msg_type = b'IMU'  # or b'CAL' - will need different min and max values.

graph_rates = True
rates_min = -200
rates_max = 200
rate_vars = ["rate_x", "rate_y", "rate_z"]

graph_accels = False
accel_min = -1.1
accel_max = 1.1
accel_vars = ["accel_x", "accel_y", "accel_z"]

plot_at_end = False
#____________________END CONFIG SECTION_____________

if connect_udp:
    board = IMUBoard()
    board.clear_inputs()
    data_connection = UDPConnection(remote_ip=A1_ip, remote_port=UDP_LOCAL_DATA_PORT, local_port=computer_port1)
    control_connection = UDPConnection(remote_ip=A1_ip, remote_port=UDP_LOCAL_CONFIG_PORT, local_port=computer_port2)
    # release com, connect with udp
    board.release_connections()
    board.data_connection = data_connection
    board.control_connection = control_connection
else:
    board = IMUBoard.auto()

board.set_cfg({"msg": msg_type})

if graph_rates:
    collector = Collector(board=board, log_messages=True, message_file_name=None,
                          log_debug=False, debug_file_name="debug.txt", log_detailed=False)
    collector.log_configurations()
    collector.start_reading()
    p = RealTimePlot(collector, rate_vars, ymin=rates_min, ymax=rates_max)
    collector.stop_reading()
    if plot_at_end:
        collector.plot_everything()
    collector.log_final_statistics()
    collector.stop_logging()

if graph_accels:
    collector = Collector(board=board, log_messages=True, message_file_name=None,
                          log_debug=False, debug_file_name="debug.txt", log_detailed=False)
    collector.log_configurations()
    collector.start_reading()
    p = RealTimePlot(collector, accel_vars, ymin=accel_min, ymax=accel_max)
    collector.stop_reading()
    if plot_at_end:
        collector.plot_everything()
    collector.log_final_statistics()
    collector.stop_logging()

board.release_connections()
