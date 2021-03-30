# import tools package by path relative to this file
import sys
import pathlib
parent_dir = str(pathlib.Path(__file__).parent)
sys.path.append(parent_dir+'/src')
from tools import *


#arguments:
# logger.py <file> "COM" "COM3"
# logger.py <file> "UDP" <A1 ip> <A1 port> <computer port>

file_name, connection_type = sys.argv[1], sys.argv[2]

if connection_type == "COM":
    port_name = sys.argv[3]
    board = IMUBoard(data_port=port_name, control_port=None)
else:
    A1_ip, A1_port, computer_port = sys.argv[3], sys.argv[4], sys.argv[5]
    board = IMUBoard()
    board.data_connection = UDPConnection(remote_ip=A1_ip, remote_port=int(A1_port), local_port=int(computer_port))

board.clear_inputs()
collector = Collector(board=board, log_messages=True, message_file_name=file_name,
                      log_debug=False, debug_file_name="debug.txt", log_detailed=False)
collector.start_reading()
