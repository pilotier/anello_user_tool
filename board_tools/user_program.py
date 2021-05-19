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
from user_program_config import *
from ioloop import *
from convertLog import export_logs# TODO - put under src directory?

parent_dir = str(pathlib.Path(__file__).parent)
sys.path.append(parent_dir+'/src')
from tools import *


#interface for A1 configuration and logging
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
        if self.con_on.value and self.connection_info:
            print("Device: "+self.pid+": "+self.serialnum+", firmware version "+self.version)

    def show_connection(self):
        con = self.connection_info
        if con and self.con_on.value:
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
    # save output in a json
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
            debug_print("data success: "+str(data_success)+", control success: "+str(control_success))
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
        #data_connection = UDPConnection(remote_ip=A1_ip, remote_port=UDP_LOCAL_DATA_PORT, local_port=data_port)
        control_connection = UDPConnection(remote_ip=A1_ip, remote_port=UDP_LOCAL_CONFIG_PORT, local_port=config_port)
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
        #skip_indices = UDP_FIELD_INDICES if self.connection_info["type"] == "UDP" else []

        options = CFG_FIELD_NAMES + ["cancel"]
        selected_index = cutie.select(options)
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

        #if connected by udp, changing udp settings can disconnect - give warning
        if code in UDP_FIELDS and self.connection_info["type"] == "UDP":
            change_anyway = cutie.prompt_yes_or_no("Changing UDP settings while connected by UDP may close the connection. Change anyway?")
            if not change_anyway:
                return

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
        actions = ["Export to CSV", "cancel"]
        if self.log_on.value:
            actions = ["Stop"]+actions
        else:
            actions = ["Start"] + actions
        selected_action = actions[cutie.select(actions)]
        if selected_action == "Export to CSV":
            export_logs() #import from convertLog.py
            show_and_pause("finished exporting")
            #TODO - handle export errors here?
        elif selected_action == "Start":
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
                port = int(cutie.get_number("port:"))
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

# pause on messages if it will refresh after
def show_and_pause(text): #UserProgram
    print(text)
    print("enter to continue:")
    input()


def clear_screen(): #UserProgram
    if not DEBUG:
        if os.name == 'nt':  # Windows
            os.system('cls')
        elif os.name == 'posix':  # Linux, Mac
            os.system('clear')
        else:
            # the only other os.name is 'java' - not sure what OS has that.
            pass


# one string of the date and time
def date_time(): #UserProgram
    return time.ctime()
    # could also make it from parts:
    # time_parts = time.localtime()
    # year = time_parts.tm_year
    # month = time_parts.tm_mon
    # and tm_hour, tm_min, tm_sec, tm_wday, tm_mday, tm_yday
    # or time.strftime(format[,t])


def proper_response(message, expected_type): #UserProgram
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
def load_udp_settings(): #UserProgram
    try:
        cache_path = os.path.join(os.path.dirname(__file__), UDP_CACHE)
        with open(cache_path, 'r') as settings_file:
            settings = json.load(settings_file)
            return settings["lip"], settings["rport1"], settings["rport2"]
    except Exception as e:
        return None


def save_udp_settings(lip, rport1, rport2): #UserProgram
    try:
        settings = {"lip": lip, "rport1": rport1, "rport2": rport2}
        cache_path = os.path.join(os.path.dirname(__file__), UDP_CACHE)
        with open(cache_path, 'w') as settings_file:
            json.dump(settings, settings_file)
    except Exception as e:
        print("error writing connection settings: "+str(e))
        return None

#not using yet: ntrip_version = 1/2 , ntrip_auth = "Basic"/"Digest"/"None"
def load_ntrip_settings(): #UserProgram
    try:
        cache_path = os.path.join(os.path.dirname(__file__), NTRIP_CACHE)
        with open(cache_path, 'r') as settings_file:
            settings = json.load(settings_file)
            return settings
    except Exception as e:
        return None

def save_ntrip_settings(settings): #UserProgram
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
    io_thread = Process(target=io_loop, args = shared_args)
    io_thread.start()
    runUserProg(*shared_args) # must do this in main thread so it can take inputs
    io_thread.join()
