import cutie
import os
import time
import sys
import pathlib
import json
import subprocess
import serial
from multiprocessing import Array, Value, Process, Manager
import base64
import socket
import select

parent_dir = str(pathlib.Path(__file__).parent)
sys.path.append(parent_dir+'/src')
from tools import *

# user tool to interact with A1
# show info at top, actions below
# after each action, refresh screen

DEBUG = False

MENU_OPTIONS = [
    "Refresh",
    "Connect",
    "Configure",
    "Log",
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
    "A-1 IP",
    "REMOTE IP",
    "REMOTE DATA PORT ",
    "REMOTE CONFIGURATION PORT"
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

UDP_FIELD_INDICES = [5, 6, 7, 8, 9]  # udp related field positions in CFG_FIELD_NAMES / CODES

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
    "odo": ["on", "off", "mps", "mph", "kph", "fps"],
    "fog": ["on", "off"],
    "dhcp": ["on", "off"]
}

#UDP constants
A1_port1 = UDP_LOCAL_DATA_PORT
A1_port2 = UDP_LOCAL_CONFIG_PORT
UDP_CACHE = "udp_settings.txt"
NTRIP_CACHE = "ntrip_settings.txt"


CONNECT_RETRIES=3
RUNNING_RETRIES=10
FLUSH_FREQUENCY = 200

class UserProgram:


    #(data_connection, logging_on, log_name, log_file, ntrip_on, ntrip_reader, ntrip_request, ntrip_ip, ntrip_port)
    def __init__(self, exitflag, con_on, con_start, con_stop, con_succeed,
                 con_type, com_port, com_baud, udp_ip, udp_port, gps_received,
                 log_on, log_start, log_stop, log_name,
                 ntrip_on, ntrip_start, ntrip_stop, ntrip_succeed,
                 ntrip_ip, ntrip_port, ntrip_gga, ntrip_req):
        self.connection_info = None
        self.board = None
        self.serialnum = ""
        self.version = ""
        self.pid = ""

        #keep the shared vars as class attributes so other UserProgram methods have them.
        #set them like self.log_name.value = x so change is shared. not self.log_name = x
        self.exitflag, self.con_on, self.con_start, self.con_stop, self.con_succeed = exitflag, con_on, con_start, con_stop, con_succeed
        self.con_type, self.com_port, self.com_baud, self.udp_ip, self.udp_port, self.gps_received =\
            con_type, com_port, com_baud, udp_ip, udp_port, gps_received
        self.log_on, self.log_start, self.log_stop, self.log_name = log_on, log_start, log_stop, log_name
        self.ntrip_on, self.ntrip_start, self.ntrip_stop, self.ntrip_succeed = ntrip_on, ntrip_start, ntrip_stop, ntrip_succeed
        self.ntrip_ip, self.ntrip_port, self.ntrip_gga, self.ntrip_req = ntrip_ip, ntrip_port, ntrip_gga, ntrip_req


    def mainloop(self):
        while True:
            try:
                clear_screen()
                self.show_info()
                print("\nSelect One:")
                action = MENU_OPTIONS[cutie.select(MENU_OPTIONS)]
                if action == "Connect":
                    self.connect()
                elif action == "Configure":
                    self.configure()
                elif action == "Log":
                    self.log()
                elif action == "NTRIP":
                    self.ntrip_menu()
                elif action == "Upgrade":
                    self.upgrade()
                elif action == "Plot":
                    self.plot()
                elif action == "Refresh":
                    self.refresh()
                elif action == "Exit":
                    self.exit()
                else:
                    raise Exception("invalid action: " + str(action))
            except (socket.error, socket.herror, socket.gaierror, socket.timeout, serial.SerialException, serial.SerialTimeoutException) as e:
                print(e)
                self.release()
                show_and_pause("connection error. check cable and reconnect")
            # #TODO - handle udp connection error, other errors

    #exit: close connections, signal iothread to exit (which will close its own connections)
    def exit(self):
        self.release()
        self.exitflag.value = 1
        exit()

    # release all connections before connecting again
    def release(self):
        self.stop_logging()
        #close_ntrip(self.ntrip_on, self.ntrip_reader)
        self.connection_info = None
        if self.board:
            self.board.release_connections()  # must release or reconnecting to the same ports will error
            self.board = None
        #signal iothread to stop data connection
        self.con_on.value = 0
        self.con_stop.value = 1

    # if we clear after every action, refresh does nothing extra
    def refresh(self):
        pass

    def show_info(self):
        print("\nAnello Python Program " + date_time())
        print("\nSystem Status:")
        self.show_device()
        self.show_connection()
        self.show_ntrip()
        self.show_logging()

    def show_device(self):
        if self.connection_info:
            print("Device: "+self.pid+": "+self.serialnum+", firmware version "+self.version)

    def show_connection(self):
        con = self.connection_info
        if con:
            # example is "A-1:SN is Connected on COM57"  - connect and get serial number?
            output = "Connection: "+con["type"]+": "
            if con["type"] == "COM":
                output += "configuration port = "+con["control port"]+", data port = "+con["data port"]
            elif con["type"] == "UDP":
                output += "ip = "+con["ip"]+", data port = "+con["port1"]+", configuration port = "+con["port2"]
            print(output)
        else:
            print("Connection: Not connected")

    def show_ntrip(self):
        if self.ntrip_on.value:  #and ntrip_target:
            ip = self.ntrip_ip.value.decode()
            port = self.ntrip_port.value
            status = "NTRIP: Connected to "+ip+":"+str(port)
        else:
            status = "NTRIP: Not connected"
        print(status)


    def show_logging(self):
        if self.log_on.value:
            # TODO - count messages logged: either read file (if safe while writing) or communicate with process
            print("Log: Logging to "+self.log_name.value.decode()) #+" ("+str(num_messages)+" messages logged )")
        else:
            print("Log: Not logging")

    # connect using com port or UDP IP and port
    # save output in a json - means it will reuse it on next program run?
    # shows current connection on top of menu options
    def connect(self):
        while True:
            control_success = False
            try:  # catch connect_com and connect_udp errors here since there is a cancel
                clear_screen()
                self.show_connection()
                options = ["COM", "UDP", "cancel"]
                selected = options[cutie.select(options)]
                if selected == "COM":
                    new_connection = self.connect_com()
                    if new_connection:
                        self.connection_info = new_connection
                        control_success = True
                    else: #connect_com failed or canceled
                        continue
                elif selected == "UDP":
                    new_connection = self.connect_udp()
                    if new_connection:
                        self.connection_info = new_connection
                        self.con_type.value = b"UDP"
                        control_success = True
                    else: #connect_udp failed or canceled
                        continue
                else: # cancel
                    return  # TODO - check if its the "return inside try" problem
            except Exception as e: # error on control connection fail - need this since con_start might not be sent
                control_success = False
                self.release()
                show_and_pause("error connecting - check connections and try again")
                continue
            self.gps_received.value = False # need to see gps message again after each connect
            #check success from ioloop. TODO - maybe check new_connection here - will be None for cancel, then dont wait
            debug_print("wait for connect success")
            while self.con_succeed.value == 0:
                time.sleep(0.1)
                # should it time out eventually?
            debug_print("done waiting")
            data_success = (self.con_succeed.value == 1) # 0 waiting, 1 succeed, 2 fail
            self.con_succeed.value = 0
            if data_success and control_success:
                return
            else:
                self.release()
                show_and_pause("error connecting - check connections and try again")
                continue

    def connect_com(self):
        print("\nConnect by COM port:")
        options = ["Auto", "Manual", "cancel"]
        selected = options[cutie.select(options)]
        if selected == "Auto":
            self.release()
            board = IMUBoard.auto(set_data_port=True)
        elif selected == "Manual":
            self.release()
            board = IMUBoard()
            board.connect_manually(set_data_port=True)
        else:  # cancel
            return
        self.board = board
        data_port_name = board.data_port_name
        board.data_connection.close()

        self.serialnum = self.retry_command(board.get_serial, []).ser.decode()
        self.version = self.retry_command(board.get_version, []).ver.decode()
        self.pid = self.retry_command(board.get_pid, []).pid.decode()

        #let io_thread do the data connection - give it the signal, close this copy
        self.com_port.value, self.com_baud.value = data_port_name.encode(), board.baud
        self.con_type.value = b"COM"
        self.con_on.value = 1
        self.con_start.value = 1
        return {"type": "COM", "control port": board.control_port_name, "data port": data_port_name}

    # connect by UDP:
    # assume we already configured by com and have set all the ip and ports
    # to connect by udp: need to enter A1's ip ("local ip") and both computer ("remote") ports matching config
        # could cache these - use remembered one or enter again.
    # config remote ip needs to match this computer
    # A1 port numbers will be constants so put them in here.

    def connect_udp(self):
        print("\nConnect by UDP port:")
        options = ["Manual", "cancel"]
        settings = load_udp_settings()
        auto_name = ""
        if settings: # only show saved option if it loads
            lip, rport1, rport2 = settings
            auto_name = "Saved: device ip = "+lip+", data port = "+str(rport1)+", configuration port = "+str(rport2)
            options = [auto_name]+options

        selected = options[cutie.select(options)]

        if settings and (selected == auto_name):
            A1_ip, data_port, config_port = lip, rport1, rport2
        elif selected == "Manual":
            print("enter udp settings: if unsure, connect by com and check configurations")
            A1_ip = input("A1 ip address: ")
            data_port = cutie.get_number('data port: ', min_value=1, max_value=65535, allow_float=False)
            config_port = cutie.get_number('configuration port: ', min_value=1, max_value=65535, allow_float=False)
        else:  # cancel
            return

        self.release()
        #data_connection = UDPConnection(remote_ip=A1_ip, remote_port=A1_port1, local_port=data_port)
        control_connection = UDPConnection(remote_ip=A1_ip, remote_port=A1_port2, local_port=config_port)
        board = IMUBoard()
        board.release_connections()
        board.control_connection = control_connection
        #board.data_connection = data_connection
        self.board = board
        #data_connection = board.data_connection
        self.serialnum = self.retry_command(board.get_serial, []).ser.decode()  # this works like a ping - error or timeout if bad connection
        self.version = self.retry_command(board.get_version, []).ver.decode()
        self.pid = self.retry_command(board.get_pid, []).pid.decode()
        if selected == "Manual":
            save_udp_settings(A1_ip, data_port, config_port)

        #send udp start info to io thread:
        self.udp_ip.value, self.udp_port.value = A1_ip.encode(), data_port
        self.con_type.value = b"UDP"
        self.con_on.value = 1
        self.con_start.value = 1
        return {"type": "UDP", "ip": A1_ip, "port1": str(data_port), "port2": str(config_port)}

    def configure(self):
        if not self.board:
            show_and_pause("Must connect before configuring")
            return
        clear_screen()
        self.read_all_configs(self.board)  # show configs automatically
        #check connection again since error can be caught in read_all_configs
        if not self.con_on.value:
            return
        #print("configure:")
        actions = ["Edit", "Done"]
        selected_action = actions[cutie.select(actions)]
        if selected_action == "Edit":
            self.set_cfg()
            self.configure()  # go back to configure screen to view/edit again. or remove this line -> main screen
        else:
            return

    def set_cfg(self):
        print("\nselect configurations to write\n")
        # hide udp settings if connected by udp. otherwise you can break the connection. or should we allow it?
        skip_indices = UDP_FIELD_INDICES if self.connection_info["type"] == "UDP" else []

        options = CFG_FIELD_NAMES + ["cancel"]
        selected_index = cutie.select(options, caption_indices=skip_indices, caption_prefix="N/A ")
        if options[selected_index] == "cancel":
            return
        args = {}
        name, code = CFG_FIELD_NAMES[selected_index], CFG_FIELD_CODES[selected_index]
        if code == "orn": # special case: choose between two common options or choose to enter it
            value = self.select_orientation()
        elif code in CFG_VALUE_OPTIONS:
            print("\nselect " + name)
            options = CFG_VALUE_OPTIONS[code]
            value = str(options[cutie.select(options)]).encode()
        else:
            print("\nenter value for " + name + " " + CFG_FIELD_EXAMPLES[code])
            value = input().encode()
        args[code] = value

        resp = self.retry_command(self.board.set_cfg_flash, [args])
        if not proper_response(resp, b'CFG'):
            show_and_pause("") # proper_response already shows error, just pause to see it.

    def select_orientation(self):
        print("\nselect orientation:")
        options = CFG_VALUE_OPTIONS["orn"]
        chosen = options[cutie.select(options)]
        if "+X+Y+Z" in chosen:
            return b'+X+Y+Z'
        elif "+Y+X-Z" in chosen:
            return b'+Y+X-Z'
        else:  # select it yourself
            print("\nenter value for orientation "+ CFG_FIELD_EXAMPLES["orn"])
            return input().encode()

    # read all configurations.
    def read_all_configs(self, board):
        resp = self.retry_command(board.get_cfg, [[]])
        if proper_response(resp, b'CFG'):
            print("Configurations:")
            for name in resp.configurations:
                if name in CFG_FIELD_CODES:
                    full_name = CFG_FIELD_NAMES[CFG_FIELD_CODES.index(name)]
                    print("\t" + full_name + ":\t" + resp.configurations[name].decode())

    # logging mode:
    # prompt for file name with default suggestion
    # stay in logging mode with indicator of # messages logged updated once/sec
    # also count NTRIP messages if connected
    # stop when esc or q is entered
    def log(self):
        clear_screen()
        self.show_logging()
        actions = ["cancel"]
        if self.log_on.value:
            actions = ["Stop"]+actions
        else:
            actions = ["Start"] + actions
        selected_action = actions[cutie.select(actions)]
        if selected_action == "Start":
            self.start_logging()
        elif selected_action == "Stop":
            self.stop_logging()
            #show_and_pause("stopped logging")
        else:
            return

    def start_logging(self):
        if self.log_on.value:
            show_and_pause("already logging")
            return
        elif not self.board:
            show_and_pause("must connect before logging")
            return
        else:
            suggested = collector.default_log_name()
            options = ["default: " + suggested, "other"]
            print("\nFile name:")
            selected_option = cutie.select(options)
            if selected_option == 0:
                chosen_name = suggested
            else:
                chosen_name = input("file name: ")
            self.log_name.value = chosen_name.encode()
            #log_file = open(log_name, 'w')
            #self.log_file = open_log_file("../logs", chosen_name) #do this in other thread
            self.log_on.value = 1
            self.log_start.value = 1

    def stop_logging(self):
        self.log_on.value = 0
        self.log_stop.value = 1 #send stop signal to other thread which will close the log

    def ntrip_menu(self):
        if self.connection_info and self.connection_info["type"] == "UDP":
            clear_screen()
            self.show_ntrip()
            options = ["cancel"]
            if self.ntrip_on.value:
                options = ["Stop"] + options
            else:
                options = ["Start"] + options
            selected = options[cutie.select(options)]
            if selected == "Start":
                self.start_ntrip()
            elif selected == "Stop":
                self.stop_ntrip()
                #close_ntrip(self.ntrip_on, self.ntrip_reader)
            else: #cancel
                return
        else:
            show_and_pause("must connect (UDP only) before starting NTRIP")
            return

    #NTRIP has Server and Port
    def start_ntrip(self):
        success = False
        clear_screen()
        while not success:
            print("Select NTRIP:")
            ntrip_settings = load_ntrip_settings()
            options = ["Manual", "cancel"]
            captions = []

            if ntrip_settings:
                #saved_string = "Saved: " + str(ntrip_settings)
                captions = range(1, 1+len(ntrip_settings))
                saved_vals = ["\t"+str(k)+": "+str(ntrip_settings[k]) for k in ntrip_settings]
                options = ["Saved: "] + saved_vals + options
            selected = options[cutie.select(options, caption_indices=captions)]
            if selected == "cancel":
                return
            elif selected == "Manual":
                caster = input("caster:")
                port = int(input("port:"))
                mountpoint = input("mountpoint:")
                username = input("username:")
                password = input("password:")
                send_gga = cutie.prompt_yes_or_no("send gga? (requires gps connection)") #TODO - do regular cutie select so style doesn't change?
                ntrip_settings = {"caster": caster, "port": port, "mountpoint": mountpoint, "username": username,
                                  "password": password, "gga": send_gga}
                save_ntrip_settings(ntrip_settings) # TODO - save later on after confirming it works?
            else: #Saved
                #TODO - if any of these missing, can't load from save - check first and hide saved option?
                caster = ntrip_settings["caster"]
                port = ntrip_settings["port"]
                mountpoint = ntrip_settings["mountpoint"]
                username = ntrip_settings["username"]
                password = ntrip_settings["password"]
                send_gga = ntrip_settings["gga"]
            # if send_gga and not self.gps_received.value:
            #     show_and_pause("wait for GPS to initialize before using NTRIP with GGA message")
            #     return

            port = int(port)
            mountpoint = mountpoint.encode()
            #ntrip_target = (caster, port)
            self.ntrip_ip.value = caster.encode()
            self.ntrip_port.value = port
            self.ntrip_gga.value = send_gga # seems to convert True/False to 1/0

            # _______NTRIP Connection Configs_______
            userAgent = b'NTRIP Anello Client'
            ntrip_version = 1
            ntrip_auth = "Basic" #TODO - add more options for these

            if ntrip_version == 1 and ntrip_auth == "Basic":
                auth_str = username + ":" + password
                auth_64 = base64.b64encode(auth_str.encode("ascii"))
                self.ntrip_req.value = b'GET /' + mountpoint + b' HTTP/1.0\r\nUser-Agent: ' + userAgent + b'\r\nAuthorization: Basic ' + auth_64 + b'\r\n\r\n'
            else:
                # TODO make request structure for NTRIP v2, other auth options.
                print("not implemented: version = " + str(ntrip_version) + ", auth = " + str(ntrip_auth))
                self.ntrip_req.value=b'' # will work as False for conditions
            #success = connect_ntrip(CONNECT_RETRIES, self.ntrip_on, self.ntrip_reader, self.ntrip_req, self.ntrip_ip, self.ntrip_port)
            #signal io_thread to connect the ntrip.
            clear_screen()
            self.ntrip_on.value = 1
            self.ntrip_start.value = 1
            #wait for success or fail message
            while self.ntrip_succeed.value == 0:
                continue
                # should it time out eventually?
            success = (self.ntrip_succeed.value == 1) # 0 waiting, 1 succeed, 2 fail
            self.ntrip_succeed.value = 0
            debug_print(success)

    #set flags and iothread will close ntrip connection
    def stop_ntrip(self):
        self.ntrip_on.value = 0
        self.ntrip_stop.value = 1

    # tell them to get bootloader exe and hex, give upgrade instructions. Will not do this automatically yet.
    # prompt to activate boot loader mode
    def upgrade(self):

        # TODO - make a user_program_config file with these strings?
        print("\nSoftware upgrade steps:")
        print("download our boot loader executable and update hex file.") #TODO say where to get them
        print("Turn on upgrade mode here. The A1 will pause until upgrade complete or power is cycled.")
        print("Run the bootloader commands in terminal:")
        print("\tHtxAurixBootLoader START TC36X 6 <data port number> 115200 0 0 0 0")
        print("\tHtxAurixBootLoader PROGRAMVERIFY <hex file name> 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFF0000 0x0")
        print("\tHtxAurixBootLoader END")
        print("For example on Windows, if the A1 uses ports COM3 through COM6, enter \"3\" for the data port number.")

        if self.board and self.connection_info["type"] == "COM":
            print("\nenter upgrade mode now? A1 will pause until bootloader executable runs or power is cycled.")
            options = ["Yes", "No"]
            selected = options[cutie.select(options)]
            if selected == "Yes":
                self.board.enter_bootloading()
                self.release()
                show_and_pause("Entered upgrade mode. Run bootloader and then reconnect.")
        else:
            show_and_pause("\nMust connect by COM port before entering upgrade mode")

    def plot(self):
        show_and_pause("Not implemented yet")

    # retry command on error responses (APERR type)
    # retry only on error codes from connection issues: no start, incomplete, checksum fail
    # don't retry on invalid field, invalid value which could happen from bad user input
    # method: the function to call. args: list of arguments
    def retry_command(self, method, args, retries=3):
        connection_errors = [1, 3, 4]
        for i in range(retries):
            output_msg = method(*args)
            if not output_msg:
                continue
            if output_msg.msgtype == b'ERR' and output_msg.msgtype in connection_errors:
                continue
            else:
                return output_msg
        #raise Exception("retry method: " + str(method) + " failed")
        # if it failed after retries, there is a connection problem
        self.release()
        show_and_pause("connection error - check cables and reconnect")

def open_log_file(location, name):
    # location needs to double any slashes \\ - otherwise we risk \b or other special characters
    location = os.path.join(os.path.dirname(__file__), location)  # make it relative to this file
    os.makedirs(location, exist_ok=True)
    full_path = os.path.join(location, name)
    try:
        return open(full_path, 'w')
    except Exception as e:
        print("error trying to open log file: "+location+"/"+name)
        return None

def connect_ntrip(num_retries, on, request, ip, port):
    errmsg = "No error"
    reader = None
    for i in range(num_retries):
        #print("retry "+str(i))
        try:
            close_ntrip(on, reader) #make sure previous connection doesn't interfere
            reader = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            error = reader.connect_ex((ip.value.decode(), port.value)) #((caster, port))
            if error == 0:  # not an error
                reader.settimeout(None)
                debug_print("sending ntrip request:\n"+request.value.decode())
                reader.sendall(request.value)
                first_resp = reader.recv(4096)
                debug_print("ntrip response:\n"+first_resp.decode() + "\n")
                # check the response codes:
                success = False
                if first_resp.find(b"SOURCETABLE 200 OK") >= 0:
                    errmsg = "wrong mountpoint (sourcetable)" # error message to show when out of retries
                elif first_resp.find(b"200 OK") >= 0:
                    debug_print("caster returns success message")
                    success = True
                elif first_resp.find(b"400 Not Found") >= 0:
                    errmsg = "wrong mountpoint (not found)"
                elif first_resp.find(b"400 Bad Request") >= 0:
                    errmsg ="wrong mountpoint (bad request)"
                elif first_resp.find(b"401 Unauthorized") >= 0:
                    errmsg ="wrong username/password"
                if success:
                    on.value = 1
                    return reader
                else:
                    continue # wrong response - retry
            else:
                errmsg = str(error)
                continue # error code: retry
        except Exception as e:
            errmsg = str(e)
            continue # exception: retry
    #out of retries: connection failed
    close_ntrip(on, reader)
    print("ntrip connection error: "+errmsg)
    return None

def close_ntrip(on, reader):
    if reader:
        reader.close()
    on.value = 0

# pause on messages if it will refresh after
def show_and_pause(text):
    print(text)
    print("enter to continue:")
    input()


def clear_screen():
    if not DEBUG:
        if os.name == 'nt':  # Windows
            os.system('cls')
        elif os.name == 'posix':  # Linux, Mac
            os.system('clear')
        else:
            # the only other os.name is 'java' - not sure what OS has that.
            pass


# one string of the date and time
def date_time():
    return time.ctime()
    # could also make it from parts:
    # time_parts = time.localtime()
    # year = time_parts.tm_year
    # month = time_parts.tm_mon
    # and tm_hour, tm_min, tm_sec, tm_wday, tm_mday, tm_yday
    # or time.strftime(format[,t])


def proper_response(message, expected_type):
    if not message:
        return False
    if not message.valid:  # actual problem with the message format or checksum fail, don't expect this
        print("\nMessage parsing error: "+message.error)
        return False
    elif message.msgtype == expected_type:
        return True
    elif message.msgtype == b'ERR':  # Error message, like if you sent a bad request
        print("\nError: " + ERROR_CODES[message.err])
        return False
    else:
        print('\nUnexpected response type: '+message.msgtype.decode())
        return False

# save and load udp settings, like IMUBoard connection cache
# TODO - should udp and com cache both go in IMUBoard? or both in user_program?
def load_udp_settings():
    try:
        cache_path = os.path.join(os.path.dirname(__file__), UDP_CACHE)
        with open(cache_path, 'r') as settings_file:
            settings = json.load(settings_file)
            return settings["lip"], settings["rport1"], settings["rport2"]
    except Exception as e:
        return None


def save_udp_settings(lip, rport1, rport2):
    try:
        settings = {"lip": lip, "rport1": rport1, "rport2": rport2}
        cache_path = os.path.join(os.path.dirname(__file__), UDP_CACHE)
        with open(cache_path, 'w') as settings_file:
            json.dump(settings, settings_file)
    except Exception as e:
        print("error writing connection settings: "+str(e))
        return None

#example ntrip settings:
#caster = b'18.222.59.138', port = 2101, mountpoint = b'HYFIX1', username = "00104", password = "t5bw9XhD"
#not using yet: ntrip_version = 1/2 , ntrip_auth = "Basic"/"Digest"/"None"
def load_ntrip_settings():
    try:
        cache_path = os.path.join(os.path.dirname(__file__), NTRIP_CACHE)
        with open(cache_path, 'r') as settings_file:
            settings = json.load(settings_file)
            return settings
    except Exception as e:
        return None

def save_ntrip_settings(settings):
    try:
        cache_path = os.path.join(os.path.dirname(__file__), NTRIP_CACHE)
        with open(cache_path, 'w') as settings_file:
            json.dump(settings, settings_file)
    except Exception as e:
        print("error writing ntrip settings: "+str(e))
        return None



#(data_connection, logging_on, log_name, log_file, ntrip_on, ntrip_reader, ntrip_request, ntrip_ip, ntrip_port)
def runUserProg(exitflag, con_on, con_start, con_stop, con_succeed,
                con_type, com_port, com_baud, udp_ip, udp_port, gps_received,
                log_on, log_start, log_stop, log_name,
                ntrip_on, ntrip_start, ntrip_stop, ntrip_succeed,
                ntrip_ip, ntrip_port, ntrip_gga, ntrip_req):
    prog = UserProgram(exitflag, con_on, con_start, con_stop, con_succeed,
                       con_type, com_port, com_baud, udp_ip, udp_port, gps_received,
                       log_on, log_start, log_stop, log_name,
                       ntrip_on, ntrip_start, ntrip_stop, ntrip_succeed,
                       ntrip_ip, ntrip_port, ntrip_gga, ntrip_req)
    prog.mainloop()

def debug_print(text):
    if DEBUG:
        print(text)

# read gps message, return bytes to send as GGA message
#ex: $GPGGA,165631.00,4810.8483085,N,01139.900759,E,1,05,01.9,+00400,M,,M,,*??<CR><LF>
#     ("time", "time"), 		get from GPS: Joe will add it. could use gps_time from GPS/INS until then.
#     ("lat", "degrees"),		from INS or GPS lat. - check if it needs to minute/second convert
#     ("NS", bytes),		convert from lat sign
#     ("lon", "degrees"),		from INS or GPS lon
#     ("EW", bytes),		from lon sign
#     ("quality", bytes),		make dummy for now. or figure out conversion: GPS fix type?(was 3) or GPS carSoln is 0,1,2 vs quality 0,1,2,4,5
#     ("numSV", int),		GPS message
#     ("HDOP", float),		use GPS PDOP
#     ("alt", float),		GPS mean sea level alt
#     ("altUnit", bytes),		fixed M
#     ("sep", float),		leave blank
#     ("sepunit", bytes),		fixed M
#     ("diffAge", float),		leave blank
#     ("diffStation", float)]	leave blank

def build_gga(gps_message):
    # dummy with correct format:
    #return b'$GNGGA,024416.00,3723.94891,N,12158.75467,W,1,12,1.09,3.9,M,-29.9,M,,*7B\r\n'
    if not gps_message or not gps_message.valid:
        # TODO - give an error here? can't make gga without the GPS message
        raise ValueError
    #time: HHMMSS.SS
    gps_time_s = gps_message.gps_time_ms * 1e-9
    utc_time = time.strftime("%H%M%S.00", time.gmtime(gps_time_s)).encode() # this loses  the fractional second - does it matter?
    # still need to convert time?

    # lat: format to DDMM.MMMMM
    lat_float = gps_message.lat
    NS = b'N' if lat_float > 0 else b'S'
    lat_deg = "{:0>2d}".format(abs(int(lat_float)))
    lat_min = "{:08.5f}".format(60 * abs(lat_float - int(lat_float)))
    lat = (lat_deg+lat_min).encode()

    # lon: format to DDDMM.MMMMM
    lon_float = gps_message.lon
    EW = b'E' if lon_float > 0 else b'W'
    lon_deg = "{:0>3d}".format(abs(int(lon_float)))
    lon_min = "{:08.5f}".format(60 * abs(lon_float - int(lon_float)))
    lon = (lon_deg+lon_min).encode()

    fixtype = b'4' #dummy - just pretend we got good fix? not sure if it matters

    # numSV: send to 2 digits
    numsv = "{:0>2d}".format(gps_message.numSV).encode()
    HDOP = str(gps_message.PDOP).encode() #not the same but should be close . P.P
    alt_msl = str(gps_message.alt_msl_m).encode()  # how many digits?
    altUnit = b'M'
    sep = b'' # ntrip example didn't have this, so skip
    sepunit = b'M'
    diffAge = b'' #example didn't have
    diffStation = b''
    # build payload. later - could assemble a Message() with the GGA fields and use ReadableScheme to build payload?
    payload = b'GNGGA,'+utc_time+b','+lat+b','+NS+b','+lon+b','+EW+b','+fixtype+b','+numsv+b','+HDOP+b','+alt_msl+b','+\
        altUnit+b','+sep+b','+sepunit+b','+diffAge+b','+diffStation
    checksum = int_to_ascii(ReadableScheme().compute_checksum(payload))
    gga_data = b'$'+payload+b'*'+checksum+b'\r\n'
    debug_print(gga_data)
    return gga_data

def io_loop(exitflag, con_on, con_start, con_stop, con_succeed,
            con_type, com_port, com_baud, udp_ip, udp_port, gps_received,
            log_on, log_start, log_stop, log_name,
            ntrip_on, ntrip_start, ntrip_stop, ntrip_succeed,
            ntrip_ip, ntrip_port, ntrip_gga, ntrip_req):
    data_connection = None
    ntrip_reader = None
    log_file = None
    flush_counter=0
    last_valid_gps = None
    ascii_scheme = ReadableScheme()

    while True:

        #first handle all start/stop signals.
        if con_stop.value: #TODO - currently not using this since I release before new connection anyway
            debug_print("io_loop con stop")
            if data_connection:
                data_connection.close()
                data_connection = None
            con_stop.value = 0
        elif log_stop.value:
            debug_print("io_loop log stop")
            if log_file:
                log_file.close()
                log_file = None
            log_stop.value = 0
        elif ntrip_stop.value:
            debug_print("io_loop ntrip stop")
            if ntrip_reader:
                ntrip_reader.close()
                ntrip_reader=None
            ntrip_stop.value = 0
        # handle exit after stops just in case.
        elif exitflag.value:
            # exit should release everything in case not released
            if data_connection:
                data_connection.close()
            if ntrip_reader:
                ntrip_reader.close()
            if log_file:
                log_file.close()
            exit()
        elif con_start.value:
            con_start.value = 0
            try:
                # release existing connection:
                if data_connection:
                    data_connection.close()
                debug_print("io_loop con start")
                if con_type.value == b"COM":
                    debug_print("io_loop connect COM")
                    data_connection = SerialConnection(com_port.value.decode(), com_baud.value)
                elif con_type.value == b"UDP":
                    debug_print("io_loop connect UDP")
                    data_connection = UDPConnection(udp_ip.value.decode(), A1_port1, udp_port.value)
                con_succeed.value = 1 # success
            except Exception:
                con_succeed.value = 2  # fail
                if data_connection:
                    data_connection.close()
        elif log_start.value:
            debug_print("io_loop log start")
            log_file = open_log_file("../logs", log_name.value.decode())
            log_start.value = 0
        elif ntrip_start.value:
            debug_print("io_loop ntrip start")
            ntrip_reader = connect_ntrip(CONNECT_RETRIES, ntrip_on, ntrip_req, ntrip_ip, ntrip_port)
            if ntrip_reader: # signal success/fail to ntrip_start in user thread
                ntrip_succeed.value = 1
            else:
                ntrip_succeed.value = 2
            ntrip_start.value = 0

        #debug_print("ioloop doing work: ntrip_on = "+str(ntrip_on.value)+", ntrip_reader = "+str(ntrip_reader))
        if ntrip_on.value and data_connection and ntrip_reader and ntrip_reader.fileno() >= 0:
            #print("ntrip work to do")
            try:
                #this select can raise ValueError when ntrip turns off, but fileno() >=0 check should prevent it.
                reads, writes, errors = select.select([ntrip_reader], [], [], 0)
                # ntrip data incoming -> take it and send to data connection.
                if ntrip_reader in reads:
                    ntrip_data = ntrip_reader.recv(1024)
                    if not ntrip_data:
                        #empty read means disconnected: go to the catch
                        raise ConnectionResetError
                    debug_print("\nntrip data (len "+str(len(ntrip_data))+"):\n")
                    #debug_print(ntrip_data)
                    data_connection.write(ntrip_data)
            except ConnectionResetError:
                debug_print("ntrip disconnected")
                ntrip_on.value = 0
                #TODO - trying to auto-reconnect here but its not working
                time.sleep(5)
                ntrip_reader = connect_ntrip(RUNNING_RETRIES, ntrip_on, ntrip_req, ntrip_ip, ntrip_port)
                if ntrip_reader:
                    debug_print("reconnected")
                else:
                    debug_print("failed to reconnect")
                    print("ntrip disconnected")
            except Exception as e: #catchall - assume its a single bad read/write. only stop if we know it disconnected.
                #print(type(e))
                continue

        # A1 has output: log it
        #if log_on.value and data_connection and data_connection.read_ready():
        if data_connection:
            try:
                #TODO - verify connection state? read_ready fails on COM if disconnected, but no error on UDP lost here
                read_ready = data_connection.read_ready()
                if read_ready: # read whether logging or not to keep buffer clear
                    in_data = data_connection.readall()
                    # if COM: data can be several messages, and partial messages: have to extract GPS message, might be split
                    # if UDP: getting one whole message at a time - due to speed, or differences in read method?
                    # for now, only using UDP for ntrip. but if using COM, need to split on \n and handle partial gps.
                    if b'GPS' in in_data:
                        #debug_print("\n<"+in_data.decode()+">")
                        # do split in case of COM, but won't use COM yet.
                        parts = in_data.split(READABLE_START)
                        for part in parts:
                            # if len(part)>0 and part[0] == READABLE_START:
                            #     part = part[1:]
                            if b'GPS' in part: #should usually be true for only one part
                                #debug_print("\n<"+part.decode()+">")
                                gps_message = Message()
                                ascii_scheme.set_fields_general(gps_message, part) #parse the gps message
                                if gps_message.valid:
                                    #debug_print("valid GPS message")
                                    last_valid_gps = gps_message # save if needed for ntrip start or delayed sending
                                    gps_received.value = 1 #will allow setting gga on in ntrip
                                    #build and send GGA message if ntrip on
                                    if ntrip_on and ntrip_reader and ntrip_gga:
                                        # build GGA
                                        gga_message = build_gga(gps_message)
                                        ntrip_reader.sendall(gga_message)
                                else:
                                    #debug_print("invalid GPS message")
                                    pass
                    if log_on and log_file: #TODO - what about close in mid-write? could pass message and close here. or catch exception
                        #pass
                        #debug_print(in_data.decode())
                        #log_file.write("< " + str(flush_counter) + " >")
                        log_file.write(in_data.decode())
                        #periodically flush so we see file size progress
                        flush_counter += 1
                        #debug_print("< "+str(flush_counter)+" >")
                        if flush_counter >= FLUSH_FREQUENCY:
                            flush_counter = 0
                            log_file.flush()
                            os.fsync(log_file.fileno())
            except (socket.error, socket.herror, socket.gaierror, socket.timeout, serial.SerialException, serial.SerialTimeoutException) as e:
                # connection errors: indicate connection lost. I only saw the the serial errors happen here.
                data_connection.close()
                con_on.value = 0

        # except KeyboardInterrupt:
        #     print("halted by user")
        #     ntrip_reader.close()
        #     connection.close()
        #     stop_logging()
        #     #cutieThread.stop()
        #     #end()
        # except Exception as e:
        #     print(e)
        #     ntrip_reader.close()
        #     connection.close()
        #     stop_logging()
        #     #end()
    # else:
    #     # could retry for connect_ex error.
    #     print("error: " +str(error))

if __name__ == "__main__":

    string_size = 500 # make Arrays big unless I find out how to resize
    #shared vars

    exitflag = Value('b', 0)
    con_on = Value('b', 0)
    con_start = Value('b', 0)
    con_stop = Value('b', 0)
    con_succeed = Value('b', 0)
    con_type = Array('c', string_size) #com/udp
    com_port = Array('c', string_size)#str
    com_baud = Value('i', 0) #int
    udp_ip = Array('c', string_size) #str
    udp_port = Value('i', 0) #int
    gps_received = Value('b', 0)
    # bundle all connection ones into one structure? same for logging / ntrip
    # or group into arrays by type: all single flags, all ints, etc

    log_on = Value('b', 0) # for current status
    log_start = Value('b', 0) # start signal
    log_stop = Value('b', 0) # stop signal
    log_name = Array('c', string_size) #Array('c', b'')

    ntrip_on = Value('b',0)
    ntrip_start = Value('b', 0)
    ntrip_stop = Value('b', 0)
    ntrip_succeed = Value('b', 0)
    ntrip_ip = Array('c', string_size)
    ntrip_port = Value('i', 0)
    ntrip_gga = Value('b', 0)
    ntrip_req = Array('c', string_size)  # b'') #probably biggest string - allocate more?

    shared_args = (exitflag, con_on, con_start, con_stop, con_succeed,
                   con_type, com_port, com_baud, udp_ip, udp_port, gps_received,
                   log_on, log_start, log_stop, log_name,
                   ntrip_on, ntrip_start, ntrip_stop, ntrip_succeed, ntrip_ip, ntrip_port, ntrip_gga, ntrip_req)
    #user_thread = Process(target=runUserProg, args = args_list)
    io_thread = Process(target=io_loop, args = shared_args)
    #user_thread.start()
    io_thread.start()
    runUserProg(*shared_args) # must do this in main thread so it can take inputs
    #user_thread.join()
    io_thread.join()