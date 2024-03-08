#demo of odometer messaging over serial with auto-detect and message generation.

#put this in user_tools/board_tools directory so the import works.
#it will automatically find the unit's serial port and create the odometer messages.
#replace "speed" with a call to your odometer

from time import sleep

import pathlib
import sys
parent_dir = str(pathlib.Path(__file__).parent)
sys.path.append(parent_dir+'/src')
from tools import *
import socket
import re
import zmq 
import json
import time
import socket
from time import sleep
from random import uniform

def calculate_checksum(data):
    checksum = 0
    for byte in data:
        checksum ^= byte
    return checksum

def validate_checksum(message):
    data, received_checksum = message.split('*')
    calculated_checksum = calculate_checksum(data[1:].encode())  # Exclude the '#' character
    return int(received_checksum, 16) == calculated_checksum

def parse_apins_message(message):
    fields = message.split(',')
    
    # Initialize a dictionary to hold the parsed data
    apins_data = {}

    # A helper function to safely convert strings to floats
    def to_float(s, default=0.0):
        try:
            return float(s)
        except ValueError:
            return default

    # A helper function to safely convert strings to ints
    def to_int(s, default=0):
        try:
            return int(s)
        except ValueError:
            return default

    # Assuming the fields list has the correct number of elements
    if len(fields) >= 14:
        apins_data = {
            'message_type': fields[0],
            'time': to_int(fields[1]),
            'gps_time_ns': to_int(fields[2]),
            'status': to_int(fields[3]),
            'lat_deg': to_float(fields[4]),
            'lon_deg': to_float(fields[5]),
            'atl_m': to_float(fields[6]),
            'velocity_north_mps': to_float(fields[7]),
            'velocity_east_mps': to_float(fields[8]),
            'velocity_down_mps': to_float(fields[9]),
            'roll_deg': to_float(fields[10]),
            'pitch_deg': to_float(fields[11]),
            'heading_deg': to_float(fields[12]),
            'ZUPT': to_int(fields[13])
        }
    else:
        print("Invalid APINS message format. Expected at least 14 fields.")

    return apins_data

def main():
    UDP_IP = "192.168.1.1"
    UDP_PORT = 1111
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind((UDP_IP, UDP_PORT))
    
    print(f"Listening for APINS messages on UDP port {UDP_PORT}...")
    
        
    print("Starting main loop...")

    while True:
        try:
            data, addr = sock.recvfrom(1024)  # buffer size is 1024 bytes
            message = data.decode('ascii', errors='ignore')
            
            if message.startswith('#') and '*' in message:
                if validate_checksum(message.strip()):
                    if message.startswith('#APINS,'):
                        apins_data = parse_apins_message(message[1:].split('*')[0])
                        print("APINS Data:", apins_data)
                else:
                    print("Invalid checksum. Message ignored.")
    
        except KeyboardInterrupt: 
            A1.release_connections() #release serial connections
            exit()
       

if __name__ == "__main__":
    main()