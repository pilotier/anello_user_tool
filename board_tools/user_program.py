import cutie
import os
import time
import sys
import pathlib
import json
import subprocess
import serial

parent_dir = str(pathlib.Path(__file__).parent)
sys.path.append(parent_dir+'/src')
from tools import *

# user tool to interact with A1
# show info at top, actions below
# after each action, refresh screen

MENU_OPTIONS = [
    "Connect",
    "Configure",
    "Log",
    "NTRIP",
    "Upgrade",
    "Plot",
    "Refresh",
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
    "GPS 1",
    "GPS 2",
    "ODOMETER",
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
    "gps2",
    "odo",
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
    "odr": [20, 50, 100, 200],
    "gps1": ["on", "off"],
    "gps2": ["on", "off"],
    "odo": ["on", "off", "mps", "mph", "kph", "fps"],
    "dhcp": ["on", "off"]
}

#UDP constants
A1_port1 = UDP_LOCAL_DATA_PORT
A1_port2 = UDP_LOCAL_CONFIG_PORT
UDP_CACHE = "udp_settings.txt"

class UserProgram:
    def __init__(self):
        self.connection_info = None
        self.ntrip = None
        self.board = None
        self.logging = False
        self.log_file_name = None
        self.logger = None
        self.serialnum = None

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
                    self.set_ntrip()
                elif action == "Upgrade":
                    self.upgrade()
                elif action == "Plot":
                    self.plot()
                elif action == "Refresh":
                    self.refresh()
                elif action == "Exit":
                    self.release()
                    exit()
                else:
                    raise Exception("invalid action: " + str(action))
            except Exception:
                self.release()
                show_and_pause("connection error. check cable and reconnect")
            #TODO - handle udp connection error, other errors

    # if we clear after every action, refresh does nothing extra
    def refresh(self):
        pass

    def show_info(self):
        print("\nAnello Python Program " + date_time())
        print("\nSystem Status:")
        self.show_connection()
        self.show_ntrip()
        self.show_logging()

    def show_connection(self):
        con = self.connection_info
        if con:
            # example is "A-1:SN is Connected on COM57"  - connect and get serial number?
            output = "Connection: A-1:"+self.serialnum+" connected by "+con["type"]+": "
            if con["type"] == "COM":
                output += "configuration port = "+con["control port"]+", data port = "+con["data port"]
            elif con["type"] == "UDP":
                output += "ip = "+con["ip"]+", data port = "+con["port1"]+", configuration port = "+con["port2"]
            print(output)
        else:
            print("Connection: A-1 not connected")

    def show_ntrip(self):
        if self.ntrip:
            print("NTRIP: Connected to "+self.ntrip["server"]+", "+self.ntrip["port"])
        else:
            print("NTRIP: Not connected")

    def show_logging(self):
        if self.logging:
            # TODO - count messages logged: either read file (if safe while writing) or communicate with process
            print("Log: Logging to "+self.log_file_name) #+" ("+str(num_messages)+" messages logged )")
        else:
            print("Log: Not logging")

    # connect using com port or UDP IP and port
    # save output in a json - means it will reuse it on next program run?
    # shows current connection on top of menu options
    def connect(self):
        while True:
            try:  # catch connect_com and connect_udp errors here since there is a cancel
                clear_screen()
                self.show_connection()
                options = ["COM", "UDP", "cancel"]
                selected = options[cutie.select(options)]
                if selected == "COM":
                    new_connection = self.connect_com()
                    self.connection_info = new_connection if new_connection else self.connection_info
                    return
                elif selected == "UDP":
                    new_connection = self.connect_udp()
                    self.connection_info = new_connection if new_connection else self.connection_info
                    return
                else: # cancel
                    return
            except Exception as e:
                self.release()
                show_and_pause("error connecting - check connections and try again")
                continue

    # release all connections before connecting again
    def release(self):
        self.stop_logging()
        self.connection_info = None
        if self.board:
            self.board.release_connections()  # must release or reconnecting to the same ports will error
            self.board = None

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
        # TODO - check connection worked before returning? or handle errors from board methods
        self.board = board
        self.serialnum = retry_command(board.get_serial, []).ser.decode()
        return {"type": "COM", "control port": board.control_port_name, "data port": board.data_port_name}

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
        data_connection = UDPConnection(remote_ip=A1_ip, remote_port=A1_port1, local_port=data_port)
        control_connection = UDPConnection(remote_ip=A1_ip, remote_port=A1_port2, local_port=config_port)
        board = IMUBoard()
        board.release_connections()
        board.control_connection = control_connection
        board.data_connection = data_connection
        self.board = board
        self.serialnum = retry_command(board.get_serial, []).ser.decode()  # this works like a ping - error or timeout if bad connection
        if selected == "Manual":
            save_udp_settings(A1_ip, data_port, config_port)
        return {"type": "UDP", "ip": A1_ip, "port1": str(data_port), "port2": str(config_port)}

    def configure(self):
        if not self.board:
            show_and_pause("Must connect before configuring")
            return
        clear_screen()
        read_all_configs(self.board)  # show configs automatically
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
        if code in CFG_VALUE_OPTIONS:
            print("\nselect " + name)
            options = CFG_VALUE_OPTIONS[code]
            value = str(options[cutie.select(options)]).encode()
        else:
            print("\nenter value for " + name + " " + CFG_FIELD_EXAMPLES[code])
            value = input().encode()
        args[code] = value

        resp = retry_command(self.board.set_cfg_flash, [args])
        if not proper_response(resp, b'CFG'):
            show_and_pause("") # proper_response already shows error, just pause to see it.

    # logging mode:
    # prompt for file name with default suggestion
    # stay in logging mode with indicator of # messages logged updated once/sec
    # also count NTRIP messages if connected
    # stop when esc or q is entered
    def log(self):
        clear_screen()
        self.show_logging()
        actions = ["cancel"]
        if self.logging:
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
        if self.logging:
            show_and_pause("already logging")
            return
        elif not self.board:
            show_and_pause("must connect before logging")
            return
        else:
            # TODO - get data port and pass to logger.
            self.board.data_connection.close()  # release the data port for logger to use
            self.logging = True
            suggested = collector.default_log_name()
            options = ["default: " + suggested, "other"]
            print("\nFile name:")
            selected_option = cutie.select(options)
            if selected_option == 0:
                file_name = suggested
            else:
                file_name = input("file name: ")
            self.log_file_name = file_name
            con_type = self.connection_info["type"]
            logger_path = os.path.join(os.path.dirname(__file__), "logger.py")
            if con_type == "COM":
                portname = self.connection_info["data port"]
                self.logger = self.pythoncall([logger_path, file_name, con_type, portname])
            else:  #UDP
                A1_ip, A1_port, computer_port = self.connection_info["ip"], A1_port1, self.connection_info["port1"],
                self.logger = self.pythoncall([logger_path, file_name, con_type, A1_ip, str(A1_port), str(computer_port)])

    # for calling logger or any other python
    def pythoncall(self, arglist):
        # see if "python" will go to python 3. if not, do "python3" explicitly
        try:
            version = subprocess.check_output("python --version", shell=True, stderr=subprocess.PIPE)
            command = 'python' if b'Python 3' in version else 'python3'  #python 2 will print "python 2..." but returns b''
        except:
            command = "python3"  # maybe python will be not recognized with only python3?
        return subprocess.Popen([command] + arglist, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    def stop_logging(self):
        if self.logging:
            self.logging = False
            if self.logger:
                self.logger.terminate()
                self.logger = None

    #NTRIP has Server and Port
    def set_ntrip(self):
        show_and_pause("not implemented yet")
        # server = input("server: ")
        # port = input("port: ")
        # # TODO - do the actual connection here
        # self.ntrip = {"server": server, "port": port}

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
        #collector = Collector(self.board, logFile=self.logging)


# pause on messages if it will refresh after
def show_and_pause(text):
    print(text)
    print("enter to continue:")
    input()


def clear_screen():
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


# read all configurations.
def read_all_configs(board):
    resp = retry_command(board.get_cfg, [[]])
    if proper_response(resp, b'CFG'):
        print("Configurations:")
        for name in resp.configurations:
            if name in CFG_FIELD_CODES:
                full_name = CFG_FIELD_NAMES[CFG_FIELD_CODES.index(name)]
                print("\t" + full_name + ":\t" + resp.configurations[name].decode())


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


# retry command on error responses (APERR type)
# retry only on error codes from connection issues: no start, incomplete, checksum fail
# don't retry on invalid field, invalid value which could happen from bad user input
# method: the function to call. args: list of arguments
def retry_command(method, args, retries=3):
    connection_errors = [1, 3, 4]
    for i in range(retries):
        output_msg = method(*args)
        if output_msg.msgtype == b'ERR' and output_msg.msgtype in connection_errors:
            continue
        else:
            return output_msg
    raise Exception("retry method: "+str(method)+" failed")

if __name__ == "__main__":
    prog = UserProgram()
    prog.mainloop()
