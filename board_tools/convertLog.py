import sys
import pathlib
parent_dir = str(pathlib.Path(__file__).parent)
sys.path.append(parent_dir+'/src')
from tools import *
import os
from tkinter import Tk
from tkinter.filedialog import askopenfilename
import json
from user_program_config import *

#default values: currently 0 for everything. could set a different value per field and message type
gps_header = ",".join(EXPORT_GPS_FIELDS)
def gps_defaults(name):
    return 0
    #return "missing"

ins_header = ",".join(EXPORT_INS_FIELDS)
def ins_defaults(name):
    return 0
    #return "missing"

imu_header = ",".join(EXPORT_IMU_FIELDS)
def imu_defaults(name):
    return 0
    #return "missing"

all_show_fields = {b'GPS': EXPORT_GPS_FIELDS, b'INS': EXPORT_INS_FIELDS, b'IMU': EXPORT_IMU_FIELDS}
all_defaults =  {b'GPS': gps_defaults, b'INS': ins_defaults, b'IMU': imu_defaults}

# formatted point feature to put in csv
def position_for_csv(msg):
    lat, lon, props = 0,0, {}
    if msg.msgtype == b'INS':
        lat = msg.lat_deg if hasattr(msg, "lat_deg") else ins_defaults("lat_deg")
        lon = msg.lon_deg if hasattr(msg, "lon_deg") else ins_defaults("lon_deg")
        try:
            fillColor = EXPORT_INS_COLORS[getattr(msg, EXPORT_INS_COLOR_BASED_ON)]
        except Exception: # missing attribute or bad value
            fillColor = EXPORT_DEFAULT_COLOR
        props = {"radius": EXPORT_INS_RADIUS, "fillColor": fillColor} # could do radius and color based on variables
    elif msg.msgtype == b'GPS':
        lat = msg.lat_deg if hasattr(msg, "lat_deg") else gps_defaults("lat_deg")
        lon = msg.lon_deg if hasattr(msg, "lon_deg") else gps_defaults("lon_deg")
        try:
            fillColor = EXPORT_GPS_COLORS[getattr(msg, EXPORT_GPS_COLOR_BASED_ON)]
        except Exception:
            fillColor = EXPORT_DEFAULT_COLOR
        props = {"radius": EXPORT_GPS_RADIUS, "fillColor": fillColor}
    geo_dict = {"type": "Point", "coordinates": [lon, lat]}
    feature_dict = {"type": "Feature", "geometry": geo_dict, "properties": props}
    return "\"" + json.dumps(feature_dict).replace("\"", "\"\"") + "\""

#format of some field in the csv:
def format_field(msgtype, var_name, value):
    # float: force decimal since Kepler.gl will turn exponential notation into "string"
    if type(value) is float:
        return "{:.10f}".format(value).rstrip('0').rstrip('.')
    # can do more conditions using var_name and msgtype here. what about time formats?
    else:
        return str(value)

def export_logs():
    rs = ReadableScheme()
    # open the targeted log file
    Tk().withdraw()
    default_dir = os.path.join(os.path.dirname(__file__), "../logs")
    input_path = askopenfilename(initialdir=default_dir, title="Select log to convert")
    if not input_path: # empty on cancel
        print("cancelled")
        exit() # in user program, return to main menu instead
    reader = open(input_path, 'rb')

    # pick name and location for output files
    input_location = os.path.dirname(input_path)
    input_filename = os.path.basename(input_path) # should it take off the .txt or other extension?
    if "." in input_filename:
        input_notype = input_filename[:input_filename.find(".")] # before the .
    else:
        input_notype = input_filename

    # create new csv files for IMU, INS, GPS messages
    export_path = os.path.join(os.path.dirname(__file__), "..", "exports", input_notype) # exports directory
    #export_subdir = "export_"+input_notype  # sub-directory for this export only
    #export_fullpath = os.path.join(export_topdir, export_subdir)
    os.makedirs(export_path, exist_ok=True)

    ins_file_path = os.path.join(export_path, "ins.csv")
    ins_out = open(ins_file_path, 'w') # will overwrite the csv if it already exists
    print("exporting to "+os.path.normpath(ins_file_path))
    ins_out.write(ins_header)

    gps_file_path = os.path.join(export_path, "gps.csv")
    print("exporting to " + os.path.normpath(gps_file_path))
    gps_out = open(gps_file_path, 'w')
    gps_out.write(gps_header)

    imu_file_path = os.path.join(export_path, "imu.csv")
    print("exporting to " + os.path.normpath(imu_file_path))
    imu_out = open(imu_file_path, 'w')
    imu_out.write(imu_header)

    all_outputs = {b'GPS': gps_out, b'INS': ins_out, b'IMU': imu_out}


    # for each line in log file (read though, split on start or end codes):
        # parse as a message: this is the most readable way of specifying fields - by names instead of index
        # put in the csv for that type
    line = reader.readline()
    line = line.strip(b'#')
    #print("line: "+line.decode())
    line_num = 0
    while line: #until read empty

        #show progress: dot per some number of lines
        line_num += 1
        if line_num % 10000 == 0:
            print(".", end="")

        m = rs.parse_message(line)
        #print(m)
        # if m and m.msgtype == b'INS' and m.data:
        #     print("type " + m.msgtype.decode() + " commas: " + str(m.data.count(b',')))
        if m and m.valid and m.msgtype in EXPORT_MESSAGE_TYPES:
            # put whichever data we want based on message type and write to the csv for that type.
            # get each att rby name so it doesn't get show message.valid, checksum_input, etc
            # TODO - make a "message fields" structure in message for the fields so its not mixed together
            out_list = []
            msgtype = m.msgtype
            defaults = all_defaults[msgtype]
            out_file = all_outputs[msgtype]

            for name in all_show_fields[msgtype]: # or show_fields[m.msgtype]
                if name == "position_geojson": #do any constructed fields which are not a message field
                    # create and add it to the list
                    out_list.append(position_for_csv(m)) # or
                # any other constructed fields: add as conditions here
                else:
                    # use the existing message field, or default value
                    if hasattr(m, name):
                        value = getattr(m, name)
                        out_list.append(format_field(msgtype, name, value))
                    else:
                        out_list.append(str(defaults(name)))
            out_line = "\n"+",".join(out_list)
            out_file.write(out_line) # outputs[m.msgtype].write(out_line)

        else:
            pass
            #print("invalid message: "+str(message))

        line = reader.readline()
        line = line.strip(b'#')
        #print("line: " + line.decode())

    reader.close()
    ins_out.close()
    gps_out.close()
    imu_out.close()


if __name__ == "__main__":
    export_logs()