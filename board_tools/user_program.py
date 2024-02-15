from math import sqrt
import os
from contextlib import redirect_stdout
#suppress prints during import. on Mac, "import PySimpleGUI" causes print which messes up cutie menu.
with open(os.devnull, "w") as f, redirect_stdout(f):
    import cutie
    import time
    import sys
    import pathlib
    import json
    #import subprocess
    import serial
    from multiprocessing import Array, Value, Process, Manager
    import base64
    import zmq
    import json
    import socket
    import select
    from user_program_config import *
    from version_num import PROGRAM_VERSION
    from ioloop import *
    import PySimpleGUI as sg
    from convertLog import export_logs_detect_format# TODO - put under src directory?
    from map.geotiler_demo import draw_map, draw_dial
    import random
    import io
    try: #get pylru if possible, otherwise will use dictionary
        import pylru
    except ModuleNotFoundError:
        pass #prints blocked here, but should indicate an error in map

    parent_dir = str(pathlib.Path(__file__).parent)
    sys.path.append(parent_dir+'/src')
    from tools import *

    import re
    import traceback
    from file_picking import pick_one_file, pick_multiple_files


#interface for A1 configuration and logging
class UserProgram:

    #(data_connection, logging_on, log_name, log_file, ntrip_on, ntrip_reader, ntrip_request, ntrip_ip, ntrip_port)
    def __init__(self, exitflag, con_on, con_start, con_stop, con_succeed,
                 con_type, com_port, com_baud, udp_ip, udp_port, gps_received,
                 log_on, log_start, log_stop, log_name,
                 ntrip_on, ntrip_start, ntrip_stop, ntrip_succeed,
                 ntrip_ip, ntrip_port, ntrip_gga, ntrip_req,
                 last_ins_msg, last_gps_msg, last_gp2_msg, last_imu_msg, last_hdg_msg,
                 last_imu_time,
                 shared_serial_number
        ):
        self.connection_info = None
        self.board = None
        self.serialnum = ""
        self.shared_serial_number = shared_serial_number
        self.shared_serial_number.value = b""
        self.version = ""
        self.product_id = ""

        #keep the shared vars as class attributes so other UserProgram methods have them.
        #set them like self.log_name.value = x so change is shared. not self.log_name = x
        self.exitflag, self.con_on, self.con_start, self.con_stop, self.con_succeed = exitflag, con_on, con_start, con_stop, con_succeed
        self.con_type, self.com_port, self.com_baud, self.udp_ip, self.udp_port, self.gps_received =\
            con_type, com_port, com_baud, udp_ip, udp_port, gps_received
        self.log_on, self.log_start, self.log_stop, self.log_name = log_on, log_start, log_stop, log_name
        self.ntrip_on, self.ntrip_start, self.ntrip_stop, self.ntrip_succeed = ntrip_on, ntrip_start, ntrip_stop, ntrip_succeed
        self.ntrip_ip, self.ntrip_port, self.ntrip_gga, self.ntrip_req = ntrip_ip, ntrip_port, ntrip_gga, ntrip_req
        self.last_ins_msg, self.last_gps_msg, self.last_gp2_msg, self.last_imu_msg, self.last_hdg_msg = last_ins_msg, last_gps_msg, last_gp2_msg, last_imu_msg, last_hdg_msg
        self.last_imu_time = last_imu_time

        #any features which might or not be there - do based on firmware version?
        self.available_configs = []
        self.show_gps_info = False

        #self.map_cache = {} #cache for map tiles. or could use lru.LRU[max_items] to avoid overfilling
        #self.map_cache = LRU(MAX_CACHE_TILES) #TODO - calculate how many tiles we can store in memory
        try:
            self.map_cache = pylru.lrucache(MAX_CACHE_TILES)
        except Exception as e:
            print("install pylru for map caching with \"pip install pylru\"")
            print(" otherwise it will use dictionary which may hurt performance")
            self.map_cache = {} #fallback to regular dict, but then it will grow without limit.

    def mainloop(self):
        while True:
            try:
                clear_screen()
                self.show_info()
                print("\nSelect One:")
                action = MENU_OPTIONS[cutie.select(MENU_OPTIONS)]
                if action == "Connect":
                    self.connect()
                elif action == "Unit Configuration":
                    self.configure()
                elif action == "Vehicle Configuration":
                    self.vehicle_configure()
                elif action == "Log":
                    self.log()
                elif action == "Monitor":
                    self.monitor()
                elif action == "NTRIP":
                    self.ntrip_menu()
                elif action == "Firmware Update":
                    self.upgrade()
                elif action == "Plot":
                    self.plot()
                elif action == "Refresh":
                    self.refresh()
                elif action == "Exit":
                    self.exit()
                elif action == "Restart Unit":
                    self.reset()
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

    # stop operations and data port before bootloader, but still need config port to send enter_bootloading command.
    def release_for_bootload(self):
        self.stop_logging()
        self.stop_ntrip()
        #self.connection_info = None #probably don't set to None - this tracks udp/com and port numbers.
        if self.board:
            #close board's data and odometer connections, keep control connection open.
            if hasattr(self.board, "data_connection"):  #setting con_stop to 1 -> ioloop will also close it.
                self.board.data_connection.close()
            if hasattr(self.board, "odometer_connection") and self.board.odometer_connection:
                self.board.odometer_connection.close()

        #signal iothread to stop data connection
        #Todo - should it signal and close, or close only, or signal only? set flags back after bootloading?
        self.con_on.value = 0
        self.con_stop.value = 1
        time.sleep(1) #wait for communications to stop - can it check for stop?

    # if we clear after every action, refresh does nothing extra
    def refresh(self):
        pass

    def show_info(self):
        print(f"\nAnello Python Program, version {PROGRAM_VERSION}, " + date_time())
        print("\nSystem Status:")
        self.show_device()
        self.show_connection()
        self.show_ntrip()
        self.show_logging()

    def show_device(self):
        if self.con_on.value and self.connection_info:
            print(
                  f"    Product type: {self.product_id}"
                  f"\n    Serial: {self.serialnum}"
                  f"\n    Firmware version: {self.version}")

    def show_connection(self):
        con = self.connection_info
        if con and self.con_on.value:
            # example is "A-1:SN is Connected on COM57"  - connect and get serial number?
            output = "    Connection: "+con["type"]+": "
            if con["type"] == "COM":
                output += "configuration port = "+con["control port"]+", data port = "+con["data port"]
            elif con["type"] == "UDP":
                output += "ip = "+con["ip"]+", data port = "+con["port1"]+", configuration port = "+con["port2"]
            print(output)
        else:
            print("    Connection: Not connected")

    def show_ntrip(self):
        if self.ntrip_on.value:  #and ntrip_target:
            ip = self.ntrip_ip.value.decode()
            port = self.ntrip_port.value
            status = "    NTRIP: Connected to "+ip+":"+str(port)
        else:
            status = "    NTRIP: Not connected"
        print(status)

    def show_logging(self):
        if self.log_on.value:
            # TODO - count messages logged: either read file (if safe while writing) or communicate with process
            print("    Log: Logging to "+self.log_name.value.decode()) #+" ("+str(num_messages)+" messages logged )")
        else:
            print("    Log: Not logging")

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
                # do stuff based on pid here since connect_udp and connect_com get the pid
                if 'IMU' in self.product_id:
                    self.show_gps_info = False  # IMU type has no GNSS info
                else:
                    self.show_gps_info = True  # default is to show everything
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
            if not board:
                return
        elif selected == "Manual":
            self.release()
            board = IMUBoard()
            manual_result = board.connect_manually(set_data_port=True)
            if manual_result is None:
                return
        else:  # cancel
            return
        self.board = board
        data_port_name = board.data_port_name
        board.data_connection.close()

        # get product info, or assume bad connection if can't read it
        if not self.product_info_on_connect(board):
            board.release_connections()
            show_and_pause("\nfailed to read product info. Check connection settings and try again.")
            return

        # let io_thread do the data connection - give it the signal, close this copy
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
            auto_name = "Saved: A-1 ip = "+lip+", computer data port = "+str(rport1)+", computer config port = "+str(rport2)
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

        # get product info, or assume bad connection if can't read it
        if not self.product_info_on_connect(board):
            board.release_connections()
            show_and_pause("\nFailed to read product info. Check connection settings and try again.")
            return

        if selected == "Manual":
            save_udp_settings(A1_ip, data_port, config_port)

        #send udp start info to io thread:
        self.udp_ip.value, self.udp_port.value = A1_ip.encode(), data_port
        self.con_type.value = b"UDP"
        self.con_on.value = 1
        self.con_start.value = 1
        return {"type": "UDP", "ip": A1_ip, "port1": str(data_port), "port2": str(config_port)}

    def product_info_on_connect(self, board):
        combinations = (
            (board.get_serial, b'SER', 'ser', 'serialnum'),
            (board.get_version, b'VER', 'ver', 'version'),
            (board.get_pid, b'PID', 'pid', 'product_id'))

        for (getter_method, msgtype, attr_name, name_here) in combinations:
            get_response = self.retry_command(method=getter_method, response_types=[msgtype])
            if hasattr(get_response, attr_name):
                setattr(self, name_here, getattr(get_response, attr_name).decode()) # self.product_id = get_response.pid.decode()
            else:
                return False  # indicate failed connection

        self.shared_serial_number.value = self.serialnum.encode()
        return True   # success if none of the reads failed

    def configure(self):
        if not self.board:
            show_and_pause("Must connect before configuring")
            return
        clear_screen()
        if not self.read_all_configs(self.board):  # show configs automatically
            return #false means read failed -> go back to menu
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

        # allow setting only the configs which come back from the read, in that order.
        field_codes = [code for code in self.available_configs if code in CFG_CODES_TO_NAMES]
        field_names = [CFG_CODES_TO_NAMES[code] for code in field_codes]

        # cutie select for index, including cancel.
        # TODO - if bidict, can do name = options[cutie.select(options)], code = dict[name] , instead of index
        options = field_names + ["cancel"]
        selected_index = cutie.select(options)
        if options[selected_index] == "cancel":
            return
        args = {}
        name, code = field_names[selected_index], field_codes[selected_index]
        if code == "aln":
            print("\nEnter alignment angles")
            value = form_aln_string_prompt()
        elif code in CFG_VALUE_OPTIONS:
            print("\nselect " + name)
            value_options = CFG_VALUE_OPTIONS[code].copy()

            # don't allow message format = binary if any sensor ranges are 0, or version below 1.2
            if code == "mfm":
                self.board.retry_unlock_flash()
                ranges = self.board.retry_get_sensor(["rr1", "rr2", "rr3", "ra1", "ra2", "ra3"])
                if ((ranges is None) or (b'0' in ranges)) and "0" in value_options:
                    value_options.remove("0")

                if (not version_greater_or_equal(self.version, "1.2.0")) and "0" in value_options:
                    value_options.remove("0")

            value_option_names = [CFG_VALUE_NAMES.get((code, opt), opt) for opt in value_options]  # cfg and vale code -> value name
            value = value_options[cutie.select(value_option_names)]
        elif code in CFG_FIELD_EXAMPLES:
            print("\nEnter value for " + name + " " + CFG_FIELD_EXAMPLES[code])
            value = input()
        else:
            print("\nEnter value for " + name)
            value = input()
        args[code] = value.encode()

        #if connected by udp, changing udp settings can disconnect - give warning
        if code in UDP_FIELDS and self.connection_info["type"] == "UDP":
            change_anyway = cutie.prompt_yes_or_no("Changing UDP settings while connected by UDP may close the connection. Change anyway?")
            if not change_anyway:
                return

        #if setting odometer unit, first set odometer to on, then set the unit
        if code == "odo":
            args2 = {"odo": b'on'}
            resp = self.retry_command(method=self.board.set_cfg_flash, args=[args2], response_types=[b'CFG', b'ERR'])

        resp = self.retry_command(method=self.board.set_cfg_flash, args=[args], response_types=[b'CFG', b'ERR'])
        if not proper_response(resp, b'CFG'):
            show_and_pause("") # proper_response already shows error, just pause to see it.

    # read and show all user configurations
    def read_all_configs(self, board):
        resp = self.retry_command(method=board.get_cfg_flash, args=[[]], response_types=[b'CFG'])
        if proper_response(resp, b'CFG'):
            configs_dict = resp.configurations
            # hide alignment config below 1.2.0
            if 'aln' in configs_dict and not version_greater_or_equal(self.version, "1.2.0"):
                del(configs_dict['aln'])

            self.available_configs = list(configs_dict.keys())
            print("Unit Configurations:")
            for cfg_field_code in configs_dict:
                if cfg_field_code in CFG_CODES_TO_NAMES:
                    full_name = CFG_CODES_TO_NAMES[cfg_field_code]
                    value_code = configs_dict[cfg_field_code].decode()
                    value_name = CFG_VALUE_NAMES.get((cfg_field_code, value_code), value_code)
                    print("\t" + full_name + ":\t" + value_name)
            return True
        else:
            show_and_pause(f"Error reading unit configs. Try again or check cables.\n")
            return False

    # wait a few seconds for baseline calibration to finish, return the vehicle configs after.
    def wait_for_baseline_calibration(self, veh_configs=None):
        if veh_configs is None:
            veh_configs = self.board.retry_get_veh_flash_all()

        # handle if baseline calibration is still going: show a message and retry every
        if 'bcal' in veh_configs:
            current_bcal = veh_configs['bcal']
            current_bcal_name = VEH_VALUE_NAMES[('bcal', current_bcal.decode())]
            # bcal 2: from lever arms, should finish quickly. 1: auto calibrate, could take a few minutes

            if current_bcal in [b"2", b"1"]:
                print(f"\nDoing baseline calibration ({current_bcal_name}): ", end="")
                start_time = time.time()
                # loop until baseline calibration done, or time limit
                while (time.time() - start_time) < BCAL_LEVER_ARM_WAIT_SECONDS:
                    print("|", end="", flush=True)  # progress indicator
                    time.sleep(0.2)
                    veh_configs = self.board.retry_get_veh_flash_all()
                    if 'bcal' in veh_configs:
                        current_bcal = veh_configs['bcal']
                    if current_bcal == b'0':  # baseline calibration finished
                        print("\nBaseline calibration finished")
                        break
                if current_bcal != b'0':
                    print(f"\n\nStill calibrating baseline ({current_bcal_name}), check vehicle configs again in a few minutes.")
        return veh_configs

    # Vehicle Configs: same pattern as user configs
    def vehicle_configure(self):
        if not self.board:
            show_and_pause("Must connect before configuring")
            return
        clear_screen()

        veh_configs = self.board.retry_get_veh_flash_all()
        veh_configs = self.wait_for_baseline_calibration(veh_configs)
        veh_read_str = self.board.read_all_veh_terminal_interface(veh_configs)

        if veh_read_str:  # show configs automatically
            print(veh_read_str)
            try:
                # check for baseline errors, show warning if too different.
                baseline_config = float(veh_configs['bsl'])
                g1x = float(veh_configs['g1x'])
                g1y = float(veh_configs['g1y'])
                g1z = float(veh_configs['g1z'])
                g2x = float(veh_configs['g2x'])
                g2y = float(veh_configs['g2y'])
                g2z = float(veh_configs['g2z'])
                calculated_baseline = sqrt(pow(g2x - g1x, 2) + pow(g2y - g1y, 2) + pow(g2z - g1z, 2))

                # warning checks for uninitialized lever arms and antenna baselines.
                # TODO - check these conditions and warning text.

                # warn if antenna lever arms are 0
                if (g1x == 0) and (g1y == 0) and (g1z == 0) and (g2x == 0) and (g2y == 0) and (g2z == 0):
                    print("\nWarning: antenna lever arms are all 0, may not have been set.")
                    print("Accurate antenna baseline is needed for dual antenna heading.")

                # warn if baseline setting is 0
                elif baseline_config == 0:
                    print("\nWarning: baseline is zero, may not have been set.")
                    print("Accurate antenna baseline is needed for dual antenna heading.")

                # warn if baseline doesn't match lever arms using absolute difference
                elif abs(baseline_config - calculated_baseline) > BASELINE_TOLERANCE_FOR_WARNING:
                    print(f"\nWarning: Antenna baseline is {baseline_config:.3f} meters,"
                          f" but should be {calculated_baseline:.3f} meters based on antenna lever arms.")
                    print(f"Please check if your antenna lever arms are accurate.")

            except KeyError:
                pass  # old firmware won't have these configs -> just skip the check
            except ValueError:
                pass  # bad read might not convert to float -> just skip?

            # check connection again since error can be caught in read_all_configs
            if not self.con_on.value:
                return

            print("")  # blank line before edit/done
            actions = ["Edit", "Done"]
            selected_action = actions[cutie.select(actions)]
            if selected_action == "Edit":
                allowed_configs = list(veh_configs.keys())
                self.board.set_veh_terminal_interface(allowed_configs)
                self.vehicle_configure()  # recursion to view/edit again until picking "done".
            else:
                return
        else:
            show_and_pause("Error reading vehicle configs. Try again or check cables."
                           "\nOld firmware versions may not have this feature.\n")

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
            print("\nSelect logs in the file picker window")
            if export_logs_detect_format():
                show_and_pause("\nfinished exporting") #show if not canceled
            else: #canceled in file picker. #TODO - handle export errors here too?
                return
        elif selected_action == "Start":
            self.start_logging()
        elif selected_action == "Stop":
            self.stop_logging()
        else: #cancel
            return

    def start_logging(self):
        if self.log_on.value:
            show_and_pause("already logging")
            return
        elif not self.board:
            show_and_pause("must connect before logging")
            return
        else:
            suggested = collector.default_log_name(self.serialnum)
            options = ["default: " + suggested, "other"]
            print("\nFile name:")
            selected_option = cutie.select(options)
            if selected_option == 0:
                chosen_name = suggested
            else:
                chosen_name = input("file name: ")
            self.log_name.value = chosen_name.encode()
            self.log_on.value = 1
            self.log_start.value = 1

    def stop_logging(self):
        self.log_on.value = 0
        self.log_stop.value = 1 #send stop signal to other thread which will close the log

    def ntrip_menu(self):
        if self.connection_info: # and self.connection_info["type"] == "UDP":
            #before A1 fw ver 0.4.3, ntrip is over udp only
            #if self.connection_info["type"] == "UDP" or version_greater_or_equal(self.version, "0.4.3"):
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
            else: #cancel
                return
            # else:
            #     show_and_pause("must connect by UDP to use NTRIP")
            #     return
        else:
            show_and_pause("must connect before starting NTRIP")
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

    def monitor(self):
        if not self.board:
            show_and_pause("connect before monitoring")
            return

        #main window freezes until monitor closes - explain that.
        clear_screen()
        print("\nMonitoring in other window. Close it to continue.")

        # prevent prints in monitor, like PySimpleGUI prints on mac
        # this didn't stop geotiler prints when no internet -> do in geotiler_demo too?
        with open(os.devnull, "w") as f, redirect_stdout(f):
            self.monitor_main()

    def monitor_main(self):

        ascii_scheme = ReadableScheme()
        binary_scheme = Binary_Scheme()
        rtcm_scheme = RTCM_Scheme()

        sg.theme(SGTHEME)

        label_font = (FONT_NAME, LABEL_FONT_SIZE)
        value_font = (FONT_NAME, VALUE_FONT_SIZE)

        #state for map updating
        current_zoom = MAP_ZOOM_DEFAULT

        # #cache for map tiles. store in here, in user_program top level, or on disk?
        # map_cache = {} #or could use lru.LRU[max_items] to avoid overfilling

        #________________TAB 1: INS data and some GPS_______________________

        #GPS and Log toggles
        gps_is_on = False
        gps_working = False
        #try:
        resp = self.retry_command(method=self.board.get_cfg, args=[["gps1"]], response_types=[b'CFG'])
        # except Exception as e:
        #     print("error in board get gps1")
        #     resp = None
        if resp is not None and hasattr(resp, "configurations"):
            gps_is_on = resp.configurations["gps1"] == b'on'
            gps_working = True
            gps_button = sg.Button(GPS_TEXT+TOGGLE_TEXT[gps_is_on], key="gps_button", enable_events=True,
                                   font=value_font, button_color=TOGGLE_COLORS[gps_is_on])
        else:
            gps_button = sg.Button(GPS_TEXT + "disabled", key="gps_button", enable_events=False,
                                   font=value_font, button_color=BUTTON_DISABLE_COLOR)
        log_button = sg.Button(LOG_TEXT+TOGGLE_TEXT[self.log_on.value], key="log_button",  enable_events=True,
                               font=value_font, button_color=TOGGLE_COLORS[self.log_on.value])

        time_since_gps_label = sg.Text("Last GPS (s): ", size=MONITOR_TIMELABEL_SIZE, font=label_font)
        time_since_gps = sg.Text(MONITOR_DEFAULT_VALUE, key="since_gps", size=MONITOR_TIME_SIZE, font=label_font)
        time_since_ins_label = sg.Text("Last INS (s): ", size=MONITOR_TIMELABEL_SIZE, font=label_font)
        time_since_ins = sg.Text(MONITOR_DEFAULT_VALUE, key="since_ins", size=MONITOR_TIME_SIZE, font=label_font)
        anello_logo = sg.Image('anello_scaled.png', size=(300,80))

        #gps message fields in the ins tab. keep these for now. they have 2 in name/key, vs ones in gps tab don't have 2
        gps_carrsoln_label2 = sg.Text("Carrier Soln:", size=MONITOR_LABEL_SIZE, font=label_font, justification=MONITOR_ALIGN)
        gps_carrsoln2 = sg.Text(MONITOR_DEFAULT_VALUE, key="gps_carrsoln2", size=MONITOR_VALUE_SIZE, font=value_font, justification=MONITOR_ALIGN)
        gps_fix_label2 = sg.Text("GPS Fix:", size=MONITOR_LABEL_SIZE, font=label_font, justification=MONITOR_ALIGN)
        gps_fix2 = sg.Text(MONITOR_DEFAULT_VALUE, key="gps_fix2", size=MONITOR_VALUE_SIZE, font=value_font, justification=MONITOR_ALIGN)
        num_sats_label2 = sg.Text("Num Sats:", size=MONITOR_LABEL_SIZE, font=label_font, justification=MONITOR_ALIGN)
        num_sats_value2 = sg.Text(MONITOR_DEFAULT_VALUE, key="num_sats2", size=MONITOR_VALUE_SIZE, font=value_font, justification=MONITOR_ALIGN)
        # carrier solution vs fix type - need both? put both for now.


        #ins data: lat, lon, vx, vy, attitude x,y,z
        lat = sg.Text(MONITOR_DEFAULT_VALUE, key="lat", size=MONITOR_VALUE_SIZE, font=value_font, justification=MONITOR_ALIGN)
        lon = sg.Text(MONITOR_DEFAULT_VALUE, key="lon", size=MONITOR_VALUE_SIZE, font=value_font, justification=MONITOR_ALIGN)
        speed = sg.Text(MONITOR_DEFAULT_VALUE, key="speed", size=MONITOR_VALUE_SIZE, font=value_font, justification=MONITOR_ALIGN)
        att0 = sg.Text(MONITOR_DEFAULT_VALUE, key="att0", size=MONITOR_VALUE_SIZE, font=value_font, justification=MONITOR_ALIGN)
        att1 = sg.Text(MONITOR_DEFAULT_VALUE, key="att1", size=MONITOR_VALUE_SIZE, font=value_font, justification=MONITOR_ALIGN)
        att2 = sg.Text(MONITOR_DEFAULT_VALUE, key="att2", size=MONITOR_VALUE_SIZE, font=value_font, justification=MONITOR_ALIGN)
        soln = sg.Text(MONITOR_DEFAULT_VALUE, key="soln", size=MONITOR_VALUE_SIZE, font=value_font, justification=MONITOR_ALIGN)
        zupt = sg.Text(MONITOR_DEFAULT_VALUE, key="zupt", size=MONITOR_VALUE_SIZE, font=value_font, justification=MONITOR_ALIGN)
        alt_value = sg.Text(MONITOR_DEFAULT_VALUE, key="altitude", size=MONITOR_VALUE_SIZE, font=value_font, justification=MONITOR_ALIGN)

        lat_label = sg.Text("Lat. (deg):", size=MONITOR_LABEL_SIZE, font=label_font, justification=MONITOR_ALIGN)
        lon_label = sg.Text("Lon. (deg):", size=MONITOR_LABEL_SIZE, font=label_font, justification=MONITOR_ALIGN)
        speed_label = sg.Text("Speed (m/s):", size=MONITOR_LABEL_SIZE, font=label_font, justification=MONITOR_ALIGN)
        att0_label = sg.Text("Roll (deg):", size=MONITOR_LABEL_SIZE, font=label_font, justification=MONITOR_ALIGN)
        att1_label = sg.Text("Pitch (deg):", size=MONITOR_LABEL_SIZE, font=label_font, justification=MONITOR_ALIGN)
        att2_label = sg.Text("Heading (deg):", size=MONITOR_LABEL_SIZE, font=label_font, justification=MONITOR_ALIGN)
        soln_label = sg.Text("Solution:", size=MONITOR_LABEL_SIZE, font=label_font, justification=MONITOR_ALIGN)
        zupt_label = sg.Text("State:", size=MONITOR_LABEL_SIZE, font=label_font, justification=MONITOR_ALIGN)
        alt_label = sg.Text("Altitude (m):", size=MONITOR_LABEL_SIZE, font=label_font, justification=MONITOR_ALIGN)

        ins_imu_time_label = sg.Text("IMU time ms:", size=MONITOR_LABEL_SIZE, font=label_font, justification=MONITOR_ALIGN)
        ins_gps_time_label = sg.Text("GPS time ns:", size=MONITOR_LABEL_SIZE, font=label_font, justification=MONITOR_ALIGN)

        ins_imu_time_value = sg.Text(MONITOR_DEFAULT_VALUE, key="ins_imu_time", size=MONITOR_VALUE_SIZE, font=value_font, justification=MONITOR_ALIGN)
        ins_gps_time_value = sg.Text(MONITOR_DEFAULT_VALUE, key="ins_gps_time", size=(30,1), font=value_font, justification="center")
        #ins_time_row_1 = [ins_imu_time_label, ins_imu_time_value]
        #ins_time_row_2 = [ins_gps_time_label, ins_gps_time_value]
        ins_time_row = [ins_imu_time_label, ins_imu_time_value, ins_gps_time_label, ins_gps_time_value]

        buttons_row = [gps_button, log_button, time_since_gps_label, time_since_gps, anello_logo]

        # latlon_row = [lat_label, lat, lon_label, lon]
        # altitude_row = [alt_label, alt_value]
        # velocity_row = [speed_label, speed, att2_label, att2]
        # att_row = [att0_label, att0, att1_label, att1]
        # gps_fix_row = [gps_carrsoln_label, gps_carrsoln, gps_fix_label, gps_fix]
        # flags_row = [soln_label, soln, zupt_label, zupt]
        # numsv_row = [num_sats_label, num_sats_value] #todo rearrange - num sats with some o the fix stuff, speed with zupt etc?
        # #tab_1_layout = [buttons_row, [sg.HSeparator()], latlon_row, velocity_row, att_row, flags_row, gps_fix_row]
        # tab_1_layout = [latlon_row, altitude_row, velocity_row, att_row, flags_row, gps_fix_row, numsv_row] #move buttons row above tab group

        latlon_row = [lat_label, lat, lon_label, lon]
        altitude_row = [alt_label, alt_value, att2_label, att2]
        att_row = [att0_label, att0, att1_label, att1]
        velocity_row = [speed_label, speed, zupt_label, zupt]
        flags_row = [soln_label, soln, num_sats_label2, num_sats_value2]
        gps_fix_row = [gps_carrsoln_label2, gps_carrsoln2, gps_fix_label2, gps_fix2]
        #tab_1_layout = [latlon_row, altitude_row, att_row, velocity_row, flags_row, gps_fix_row, ins_time_row_1, ins_time_row_2]
        tab_1_layout = [ins_time_row, latlon_row, altitude_row, att_row, velocity_row, flags_row, gps_fix_row]
        ins_tab = sg.Tab(MONITOR_INS_TAB_TITLE, tab_1_layout, key="numbers-tab")#, title_color='Red', background_color='Green', element_justification='center')

        # ________________TAB 2: IMU Data_______________________

        ax_value = sg.Text(MONITOR_DEFAULT_VALUE, key="ax_value", size=MONITOR_VALUE_SIZE, font=value_font, justification=MONITOR_ALIGN)
        ay_value = sg.Text(MONITOR_DEFAULT_VALUE, key="ay_value", size=MONITOR_VALUE_SIZE, font=value_font, justification=MONITOR_ALIGN)
        az_value = sg.Text(MONITOR_DEFAULT_VALUE, key="az_value", size=MONITOR_VALUE_SIZE, font=value_font, justification=MONITOR_ALIGN)
        wx_value = sg.Text(MONITOR_DEFAULT_VALUE, key="wx_value", size=MONITOR_VALUE_SIZE, font=value_font, justification=MONITOR_ALIGN)
        wy_value = sg.Text(MONITOR_DEFAULT_VALUE, key="wy_value", size=MONITOR_VALUE_SIZE, font=value_font, justification=MONITOR_ALIGN)
        wz_value = sg.Text(MONITOR_DEFAULT_VALUE, key="wz_value", size=MONITOR_VALUE_SIZE, font=value_font, justification=MONITOR_ALIGN)
        fog_value = sg.Text(MONITOR_DEFAULT_VALUE, key="fog_value", size=MONITOR_VALUE_SIZE, font=value_font, justification=MONITOR_ALIGN)
        temp_value = sg.Text(MONITOR_DEFAULT_VALUE, key="temp_value", size=MONITOR_VALUE_SIZE, font=value_font, justification=MONITOR_ALIGN)
        odo_value = sg.Text(MONITOR_DEFAULT_VALUE, key="odo_value", size=MONITOR_VALUE_SIZE, font=value_font, justification=MONITOR_ALIGN)

        imu_time_value = sg.Text(MONITOR_DEFAULT_VALUE, key="imu_cpu_time", size=MONITOR_VALUE_SIZE, font=value_font, justification=MONITOR_ALIGN)
        imu_sync_value = sg.Text(MONITOR_DEFAULT_VALUE, key="imu_sync_time", size=MONITOR_VALUE_SIZE, font=value_font, justification=MONITOR_ALIGN)

        ax_label = sg.Text("Accel x (g):", size=MONITOR_LABEL_SIZE, font=label_font, justification=MONITOR_ALIGN)
        ay_label = sg.Text("Accel y (g):", size=MONITOR_LABEL_SIZE, font=label_font, justification=MONITOR_ALIGN)
        az_label = sg.Text("Accel z (g):", size=MONITOR_LABEL_SIZE, font=label_font, justification=MONITOR_ALIGN)
        wx_label = sg.Text("MEMS Rate x (deg/s):", size=MONITOR_LABEL_SIZE, font=label_font, justification=MONITOR_ALIGN)
        wy_label = sg.Text("MEMS Rate y (deg/s):", size=MONITOR_LABEL_SIZE, font=label_font, justification=MONITOR_ALIGN)
        wz_label = sg.Text("MEMS Rate z (deg/s):", size=MONITOR_LABEL_SIZE, font=label_font, justification=MONITOR_ALIGN)
        fog_label = sg.Text("FOG Rate z (deg/s):", size=MONITOR_LABEL_SIZE, font=label_font, justification=MONITOR_ALIGN)
        temp_label = sg.Text("Temperature (C):", size=MONITOR_LABEL_SIZE, font=label_font, justification=MONITOR_ALIGN)
        odo_label = sg.Text("Odometer Speed (m/s):", size=MONITOR_LABEL_SIZE, font=label_font, justification=MONITOR_ALIGN)

        imu_time_label = sg.Text("IMU time ms:", size=MONITOR_LABEL_SIZE, font=label_font, justification=MONITOR_ALIGN)
        imu_sync_label = sg.Text("Sync time ms:", size=MONITOR_LABEL_SIZE, font=label_font, justification=MONITOR_ALIGN)

        # accel_row = [ax_label, ax_value, ay_label, ay_value, az_label, az_value]
        # mems_rate_row = [wx_label, wx_value, wy_label, wy_value, wz_label, wz_value]
        mems_x_row = [ax_label, ax_value, wx_label, wx_value]
        mems_y_row = [ay_label, ay_value, wy_label, wy_value]
        mems_z_row = [az_label, az_value, wz_label, wz_value]
        fog_row = [temp_label, temp_value, fog_label, fog_value]
        odo_row = [odo_label, odo_value]
        imu_time_row = [imu_time_label, imu_time_value, imu_sync_label, imu_sync_value]
        #imu_tab_layout = [accel_row, mems_rate_row, fog_row]
        imu_tab_layout = [imu_time_row, mems_x_row, mems_y_row, mems_z_row, fog_row, odo_row]
        imu_tab = sg.Tab(MONITOR_IMU_TAB_TITLE, imu_tab_layout, key="imu-tab")

        #________________TAB 3: GPS Data __________________

        #gps message fields - also some are in ins tab: gps_carrsoln, gps_fix, num_sats_value
        gps_lat_label = sg.Text("GPS Lat (deg):", size=MONITOR_LABEL_SIZE, font=label_font, justification=MONITOR_ALIGN)
        gps_lon_label = sg.Text("GPS Lon (deg):", size=MONITOR_LABEL_SIZE, font=label_font, justification=MONITOR_ALIGN)
        gps_elipsoid_label = sg.Text("Alt Ellipsoid (m):", size=MONITOR_LABEL_SIZE, font=label_font, justification=MONITOR_ALIGN)
        gps_msl_label = sg.Text("Alt MSL (m):", size=MONITOR_LABEL_SIZE, font=label_font, justification=MONITOR_ALIGN)
        gps_speed_label = sg.Text("GPS Speed (m/s):", size=MONITOR_LABEL_SIZE, font=label_font, justification=MONITOR_ALIGN)
        gps_heading_label = sg.Text("GPS Heading (deg):", size=MONITOR_LABEL_SIZE, font=label_font, justification=MONITOR_ALIGN)
        gps_hacc_label = sg.Text("Horizontal Acccuracy (m):", size=MONITOR_LABEL_SIZE, font=label_font, justification=MONITOR_ALIGN)
        gps_vacc_label = sg.Text("Vertical Accuracy (m):", size=MONITOR_LABEL_SIZE, font=label_font, justification=MONITOR_ALIGN)
        gps_pdop_label = sg.Text("PDOP:", size=MONITOR_LABEL_SIZE, font=label_font, justification=MONITOR_ALIGN)
        gps_fix_label = sg.Text("GPS Fix:", size=MONITOR_LABEL_SIZE, font=label_font, justification=MONITOR_ALIGN)
        gps_numsv_label = sg.Text("Num Sats:", size=MONITOR_LABEL_SIZE, font=label_font, justification=MONITOR_ALIGN)
        gps_carrsoln_label = sg.Text("GPS Carrier Solution:", size=MONITOR_LABEL_SIZE, font=label_font, justification=MONITOR_ALIGN)
        gps_spd_acc_label = sg.Text("GPS Speed Accuracy:", size=MONITOR_LABEL_SIZE, font=label_font, justification=MONITOR_ALIGN)
        gps_hdg_acc_label = sg.Text("GPS Heading Accuracy:", size=MONITOR_LABEL_SIZE, font=label_font, justification=MONITOR_ALIGN)
        #[gps_lat_label,gps_lon_label,gps_elipsoid_label,gps_msl_label,gps_speed_label,gps_heading_label,gps_hacc_label,gps_vacc_label,gps_pdop_label,gps_fix_label,gps_numsv_label,gps_carrsoln_label,gps_spd_acc_label,gps_hdg_acc_label]

        gps_lat_value = sg.Text(MONITOR_DEFAULT_VALUE, key="gps_lat", size=MONITOR_VALUE_SIZE, font=value_font,justification=MONITOR_ALIGN)
        gps_lon_value = sg.Text(MONITOR_DEFAULT_VALUE, key="gps_lon", size=MONITOR_VALUE_SIZE, font=value_font,justification=MONITOR_ALIGN)
        gps_elipsoid_value = sg.Text(MONITOR_DEFAULT_VALUE, key="gps_alt_ell", size=MONITOR_VALUE_SIZE, font=value_font,justification=MONITOR_ALIGN)
        gps_msl_value = sg.Text(MONITOR_DEFAULT_VALUE, key="gps_alt_msl", size=MONITOR_VALUE_SIZE, font=value_font,justification=MONITOR_ALIGN)
        gps_speed_value = sg.Text(MONITOR_DEFAULT_VALUE, key="gps_spd", size=MONITOR_VALUE_SIZE, font=value_font,justification=MONITOR_ALIGN)
        gps_heading_value = sg.Text(MONITOR_DEFAULT_VALUE, key="gps_hdg", size=MONITOR_VALUE_SIZE, font=value_font,justification=MONITOR_ALIGN)
        gps_hacc_value = sg.Text(MONITOR_DEFAULT_VALUE, key="gps_hacc", size=MONITOR_VALUE_SIZE, font=value_font,justification=MONITOR_ALIGN)
        gps_vacc_value = sg.Text(MONITOR_DEFAULT_VALUE, key="gps_vacc", size=MONITOR_VALUE_SIZE, font=value_font,justification=MONITOR_ALIGN)
        gps_pdop_value = sg.Text(MONITOR_DEFAULT_VALUE, key="gps_pdop", size=MONITOR_VALUE_SIZE, font=value_font,justification=MONITOR_ALIGN)
        gps_fix_value = sg.Text(MONITOR_DEFAULT_VALUE, key="gps_fix", size=MONITOR_VALUE_SIZE, font=value_font,justification=MONITOR_ALIGN)
        gps_numsv_value = sg.Text(MONITOR_DEFAULT_VALUE, key="gps_numsv", size=MONITOR_VALUE_SIZE, font=value_font,justification=MONITOR_ALIGN)
        gps_carrsoln_value = sg.Text(MONITOR_DEFAULT_VALUE, key="gps_carrsoln", size=MONITOR_VALUE_SIZE, font=value_font,justification=MONITOR_ALIGN)
        gps_spd_acc_value = sg.Text(MONITOR_DEFAULT_VALUE, key="gps_spd_acc", size=MONITOR_VALUE_SIZE, font=value_font,justification=MONITOR_ALIGN)
        gps_hdg_acc_value = sg.Text(MONITOR_DEFAULT_VALUE, key="gps_hdg_acc", size=MONITOR_VALUE_SIZE, font=value_font,justification=MONITOR_ALIGN)
        #gps_lat_value,gps_lon_value,gps_elipsoid_value,gps_msl_value,gps_speed_value,gps_heading_value,gps_hacc_value,gps_vacc_value,gps_pdop_value,gps_fix_value,gps_numsv_value,gps_carrsoln_value,gps_spd_acc_value,gps_hdg_acc_value

        # #heading message fields
        # hdg_heading_value = sg.Text(MONITOR_DEFAULT_VALUE, key="hdg_hdg", size=MONITOR_VALUE_SIZE, font=value_font, justification=MONITOR_ALIGN)
        # hdg_length_value = sg.Text(MONITOR_DEFAULT_VALUE, key="hdg_len", size=MONITOR_VALUE_SIZE, font=value_font, justification=MONITOR_ALIGN)
        # hdg_flags_value = sg.Text(MONITOR_DEFAULT_VALUE, key="hdg_flags", size=MONITOR_VALUE_SIZE, font=value_font, justification=MONITOR_ALIGN)
        #
        # hdg_heading_label = sg.Text("Dual Ant. Heading (deg):", size=MONITOR_LABEL_SIZE, font=label_font, justification=MONITOR_ALIGN)
        # hdg_length_label = sg.Text("Dual Ant. Length (m):", size=MONITOR_LABEL_SIZE, font=label_font, justification=MONITOR_ALIGN)
        # hdg_flags_label = sg.Text("Dual Ant. Flags:", size=MONITOR_LABEL_SIZE, font=label_font, justification=MONITOR_ALIGN)

        gps_row1 = [gps_lat_label, gps_lat_value, gps_lon_label, gps_lon_value]
        gps_row2 = [gps_elipsoid_label, gps_elipsoid_value, gps_msl_label, gps_msl_value]
        gps_row3 = [gps_speed_label, gps_speed_value, gps_heading_label, gps_heading_value]
        gps_row4 = [gps_spd_acc_label, gps_spd_acc_value, gps_hdg_acc_label, gps_hdg_acc_value]
        gps_row5 = [gps_hacc_label, gps_hacc_value, gps_vacc_label, gps_vacc_value]
        gps_row6 = [gps_pdop_label, gps_pdop_value, gps_fix_label, gps_fix_value]
        gps_row7 = [gps_numsv_label, gps_numsv_value, gps_carrsoln_label, gps_carrsoln_value]
        # hdg_row1 = [hdg_heading_label, hdg_heading_value, hdg_length_label, hdg_length_value]
        # hdg_row2 = [hdg_flags_label, hdg_flags_value]
        gps_tab_layout = [gps_row1, gps_row2, gps_row3, gps_row4, gps_row5, gps_row6, gps_row7] #, hdg_row1, hdg_row2]
        gps_tab = sg.Tab(MONITOR_GPS_TAB_TITLE, gps_tab_layout, key="gps-tab")

        #________________TAB 4: GP2 data - looks same as GPS?_______________________

        # gp2 message fields - also some are in ins tab: gp2_carrsoln, gp2_fix, num_sats_value
        gp2_lat_label = sg.Text("GP2 Lat (deg):", size=MONITOR_LABEL_SIZE, font=label_font, justification=MONITOR_ALIGN)
        gp2_lon_label = sg.Text("GP2 Lon (deg):", size=MONITOR_LABEL_SIZE, font=label_font, justification=MONITOR_ALIGN)
        gp2_elipsoid_label = sg.Text("Alt Ellipsoid (m):", size=MONITOR_LABEL_SIZE, font=label_font,
                                     justification=MONITOR_ALIGN)
        gp2_msl_label = sg.Text("Alt MSL (m):", size=MONITOR_LABEL_SIZE, font=label_font, justification=MONITOR_ALIGN)
        gp2_speed_label = sg.Text("GP2 Speed (m/s):", size=MONITOR_LABEL_SIZE, font=label_font,
                                  justification=MONITOR_ALIGN)
        gp2_heading_label = sg.Text("GP2 Heading (deg):", size=MONITOR_LABEL_SIZE, font=label_font,
                                    justification=MONITOR_ALIGN)
        gp2_hacc_label = sg.Text("Horizontal Acccuracy (m):", size=MONITOR_LABEL_SIZE, font=label_font,
                                 justification=MONITOR_ALIGN)
        gp2_vacc_label = sg.Text("Vertical Accuracy (m):", size=MONITOR_LABEL_SIZE, font=label_font,
                                 justification=MONITOR_ALIGN)
        gp2_pdop_label = sg.Text("PDOP:", size=MONITOR_LABEL_SIZE, font=label_font, justification=MONITOR_ALIGN)
        gp2_fix_label = sg.Text("GP2 Fix:", size=MONITOR_LABEL_SIZE, font=label_font, justification=MONITOR_ALIGN)
        gp2_numsv_label = sg.Text("Num Sats:", size=MONITOR_LABEL_SIZE, font=label_font, justification=MONITOR_ALIGN)
        gp2_carrsoln_label = sg.Text("GP2 Carrier Solution:", size=MONITOR_LABEL_SIZE, font=label_font,
                                     justification=MONITOR_ALIGN)
        gp2_spd_acc_label = sg.Text("GP2 Speed Accuracy:", size=MONITOR_LABEL_SIZE, font=label_font,
                                    justification=MONITOR_ALIGN)
        gp2_hdg_acc_label = sg.Text("GP2 Heading Accuracy:", size=MONITOR_LABEL_SIZE, font=label_font,
                                    justification=MONITOR_ALIGN)
        # [gp2_lat_label,gp2_lon_label,gp2_elipsoid_label,gp2_msl_label,gp2_speed_label,gp2_heading_label,gp2_hacc_label,gp2_vacc_label,gp2_pdop_label,gp2_fix_label,gp2_numsv_label,gp2_carrsoln_label,gp2_spd_acc_label,gp2_hdg_acc_label]

        gp2_lat_value = sg.Text(MONITOR_DEFAULT_VALUE, key="gp2_lat", size=MONITOR_VALUE_SIZE, font=value_font,
                                justification=MONITOR_ALIGN)
        gp2_lon_value = sg.Text(MONITOR_DEFAULT_VALUE, key="gp2_lon", size=MONITOR_VALUE_SIZE, font=value_font,
                                justification=MONITOR_ALIGN)
        gp2_elipsoid_value = sg.Text(MONITOR_DEFAULT_VALUE, key="gp2_alt_ell", size=MONITOR_VALUE_SIZE, font=value_font,
                                     justification=MONITOR_ALIGN)
        gp2_msl_value = sg.Text(MONITOR_DEFAULT_VALUE, key="gp2_alt_msl", size=MONITOR_VALUE_SIZE, font=value_font,
                                justification=MONITOR_ALIGN)
        gp2_speed_value = sg.Text(MONITOR_DEFAULT_VALUE, key="gp2_spd", size=MONITOR_VALUE_SIZE, font=value_font,
                                  justification=MONITOR_ALIGN)
        gp2_heading_value = sg.Text(MONITOR_DEFAULT_VALUE, key="gp2_hdg", size=MONITOR_VALUE_SIZE, font=value_font,
                                    justification=MONITOR_ALIGN)
        gp2_hacc_value = sg.Text(MONITOR_DEFAULT_VALUE, key="gp2_hacc", size=MONITOR_VALUE_SIZE, font=value_font,
                                 justification=MONITOR_ALIGN)
        gp2_vacc_value = sg.Text(MONITOR_DEFAULT_VALUE, key="gp2_vacc", size=MONITOR_VALUE_SIZE, font=value_font,
                                 justification=MONITOR_ALIGN)
        gp2_pdop_value = sg.Text(MONITOR_DEFAULT_VALUE, key="gp2_pdop", size=MONITOR_VALUE_SIZE, font=value_font,
                                 justification=MONITOR_ALIGN)
        gp2_fix_value = sg.Text(MONITOR_DEFAULT_VALUE, key="gp2_fix", size=MONITOR_VALUE_SIZE, font=value_font,
                                justification=MONITOR_ALIGN)
        gp2_numsv_value = sg.Text(MONITOR_DEFAULT_VALUE, key="gp2_numsv", size=MONITOR_VALUE_SIZE, font=value_font,
                                  justification=MONITOR_ALIGN)
        gp2_carrsoln_value = sg.Text(MONITOR_DEFAULT_VALUE, key="gp2_carrsoln", size=MONITOR_VALUE_SIZE,
                                     font=value_font, justification=MONITOR_ALIGN)
        gp2_spd_acc_value = sg.Text(MONITOR_DEFAULT_VALUE, key="gp2_spd_acc", size=MONITOR_VALUE_SIZE, font=value_font,
                                    justification=MONITOR_ALIGN)
        gp2_hdg_acc_value = sg.Text(MONITOR_DEFAULT_VALUE, key="gp2_hdg_acc", size=MONITOR_VALUE_SIZE, font=value_font,
                                    justification=MONITOR_ALIGN)
        # gp2_lat_value,gp2_lon_value,gp2_elipsoid_value,gp2_msl_value,gp2_speed_value,gp2_heading_value,gp2_hacc_value,gp2_vacc_value,gp2_pdop_value,gp2_fix_value,gp2_numsv_value,gp2_carrsoln_value,gp2_spd_acc_value,gp2_hdg_acc_value

        # #heading message fields
        # hdg_heading_value = sg.Text(MONITOR_DEFAULT_VALUE, key="hdg_hdg", size=MONITOR_VALUE_SIZE, font=value_font, justification=MONITOR_ALIGN)
        # hdg_length_value = sg.Text(MONITOR_DEFAULT_VALUE, key="hdg_len", size=MONITOR_VALUE_SIZE, font=value_font, justification=MONITOR_ALIGN)
        # hdg_flags_value = sg.Text(MONITOR_DEFAULT_VALUE, key="hdg_flags", size=MONITOR_VALUE_SIZE, font=value_font, justification=MONITOR_ALIGN)
        #
        # hdg_heading_label = sg.Text("Dual Ant. Heading (deg):", size=MONITOR_LABEL_SIZE, font=label_font, justification=MONITOR_ALIGN)
        # hdg_length_label = sg.Text("Dual Ant. Length (m):", size=MONITOR_LABEL_SIZE, font=label_font, justification=MONITOR_ALIGN)
        # hdg_flags_label = sg.Text("Dual Ant. Flags:", size=MONITOR_LABEL_SIZE, font=label_font, justification=MONITOR_ALIGN)

        gp2_row1 = [gp2_lat_label, gp2_lat_value, gp2_lon_label, gp2_lon_value]
        gp2_row2 = [gp2_elipsoid_label, gp2_elipsoid_value, gp2_msl_label, gp2_msl_value]
        gp2_row3 = [gp2_speed_label, gp2_speed_value, gp2_heading_label, gp2_heading_value]
        gp2_row4 = [gp2_spd_acc_label, gp2_spd_acc_value, gp2_hdg_acc_label, gp2_hdg_acc_value]
        gp2_row5 = [gp2_hacc_label, gp2_hacc_value, gp2_vacc_label, gp2_vacc_value]
        gp2_row6 = [gp2_pdop_label, gp2_pdop_value, gp2_fix_label, gp2_fix_value]
        gp2_row7 = [gp2_numsv_label, gp2_numsv_value, gp2_carrsoln_label, gp2_carrsoln_value]
        # hdg_row1 = [hdg_heading_label, hdg_heading_value, hdg_length_label, hdg_length_value]
        # hdg_row2 = [hdg_flags_label, hdg_flags_value]
        gp2_tab_layout = [gp2_row1, gp2_row2, gp2_row3, gp2_row4, gp2_row5, gp2_row6, gp2_row7]  # , hdg_row1, hdg_row2]
        gp2_tab = sg.Tab(MONITOR_GP2_TAB_TITLE, gp2_tab_layout, key="gp2-tab")
        

        #________________TAB 5: Dual Antenna Heading_______________________

        #heading message fields
        hdg_heading_value = sg.Text(MONITOR_DEFAULT_VALUE, key="hdg_hdg", size=MONITOR_VALUE_SIZE, font=value_font, justification=MONITOR_ALIGN)
        hdg_length_value = sg.Text(MONITOR_DEFAULT_VALUE, key="hdg_len", size=MONITOR_VALUE_SIZE, font=value_font, justification=MONITOR_ALIGN)
        hdg_north_value = sg.Text(MONITOR_DEFAULT_VALUE, key="hdg_N", size=MONITOR_VALUE_SIZE, font=value_font, justification=MONITOR_ALIGN)
        hdg_east_value = sg.Text(MONITOR_DEFAULT_VALUE, key="hdg_E", size=MONITOR_VALUE_SIZE, font=value_font,justification=MONITOR_ALIGN)
        hdg_down_value = sg.Text(MONITOR_DEFAULT_VALUE, key="hdg_D", size=MONITOR_VALUE_SIZE, font=value_font,justification=MONITOR_ALIGN)
        hdg_len_acc_value = sg.Text(MONITOR_DEFAULT_VALUE, key="hdg_lenacc", size=MONITOR_VALUE_SIZE, font=value_font,justification=MONITOR_ALIGN)
        hdg_hdg_acc_value = sg.Text(MONITOR_DEFAULT_VALUE, key="hdg_hdgacc", size=MONITOR_VALUE_SIZE, font=value_font,justification=MONITOR_ALIGN)
        hdg_flags_value = sg.Text(MONITOR_DEFAULT_VALUE, key="hdg_flags", size=MONITOR_VALUE_SIZE, font=value_font, justification=MONITOR_ALIGN)
        #put the individual flags here?
        hdg_flags_fixok_value = sg.Text(MONITOR_DEFAULT_VALUE, key="hdg_flags_fixok", size=MONITOR_VALUE_SIZE, font=value_font, justification=MONITOR_ALIGN)
        hdg_flags_diffsoln_value = sg.Text(MONITOR_DEFAULT_VALUE, key="hdg_flags_diffsoln", size=MONITOR_VALUE_SIZE, font=value_font, justification=MONITOR_ALIGN)
        hdg_flags_posvalid_value = sg.Text(MONITOR_DEFAULT_VALUE, key="hdg_flags_posvalid", size=MONITOR_VALUE_SIZE, font=value_font, justification=MONITOR_ALIGN)
        hdg_flags_ismoving_value = sg.Text(MONITOR_DEFAULT_VALUE, key="hdg_flags_ismoving", size=MONITOR_VALUE_SIZE, font=value_font, justification=MONITOR_ALIGN)
        hdg_flags_refposmiss_value = sg.Text(MONITOR_DEFAULT_VALUE, key="hdg_flags_refposmiss", size=MONITOR_VALUE_SIZE, font=value_font, justification=MONITOR_ALIGN)
        hdg_flags_refobsmiss_value = sg.Text(MONITOR_DEFAULT_VALUE, key="hdg_flags_refobsmiss", size=MONITOR_VALUE_SIZE, font=value_font, justification=MONITOR_ALIGN)
        hdg_flags_hdgvalid_value = sg.Text(MONITOR_DEFAULT_VALUE, key="hdg_flags_hdgvalid", size=MONITOR_VALUE_SIZE, font=value_font, justification=MONITOR_ALIGN)
        hdg_flags_normalized_value = sg.Text(MONITOR_DEFAULT_VALUE, key="hdg_flags_normalized", size=MONITOR_VALUE_SIZE, font=value_font, justification=MONITOR_ALIGN)
        hdg_flags_carrsoln_value = sg.Text(MONITOR_DEFAULT_VALUE, key="hdg_flags_carrsoln", size=MONITOR_VALUE_SIZE, font=value_font, justification=MONITOR_ALIGN)

        hdg_heading_label = sg.Text("Dual Ant. Heading (deg):", size=MONITOR_LABEL_SIZE, font=label_font, justification=MONITOR_ALIGN)
        hdg_length_label = sg.Text("Dual Ant. Length (m):", size=MONITOR_LABEL_SIZE, font=label_font, justification=MONITOR_ALIGN)
        hdg_north_label = sg.Text("Rel. Pos. North (m):", size=MONITOR_LABEL_SIZE, font=label_font, justification=MONITOR_ALIGN)
        hdg_east_label = sg.Text("Rel. Pos. East (m):", size=MONITOR_LABEL_SIZE, font=label_font, justification=MONITOR_ALIGN)
        hdg_down_label = sg.Text("Rel. Pos. Down (m):", size=MONITOR_LABEL_SIZE, font=label_font, justification=MONITOR_ALIGN)
        hdg_len_acc_label = sg.Text("Length Accuracy (m):", size=MONITOR_LABEL_SIZE, font=label_font, justification=MONITOR_ALIGN)
        hdg_hdg_acc_label = sg.Text("Heading Accuracy (deg):", size=MONITOR_LABEL_SIZE, font=label_font, justification=MONITOR_ALIGN)
        hdg_flags_label = sg.Text("Dual Ant. Flags:", size=MONITOR_LABEL_SIZE, font=label_font, justification=MONITOR_ALIGN)
        #flags
        hdg_flags_fixok_label = sg.Text("Fix OK Flag:", size=MONITOR_LABEL_SIZE, font=label_font, justification=MONITOR_ALIGN)
        hdg_flags_diffsoln_label = sg.Text("Diff Soln Flag:", size=MONITOR_LABEL_SIZE, font=label_font, justification=MONITOR_ALIGN)
        hdg_flags_posvalid_label = sg.Text("Pos Valid Flag:", size=MONITOR_LABEL_SIZE, font=label_font, justification=MONITOR_ALIGN)
        hdg_flags_ismoving_label = sg.Text("Is Moving Flag:", size=MONITOR_LABEL_SIZE, font=label_font, justification=MONITOR_ALIGN)
        hdg_flags_refposmiss_label = sg.Text("Ref Pos Miss Flag:", size=MONITOR_LABEL_SIZE, font=label_font, justification=MONITOR_ALIGN)
        hdg_flags_refobsmiss_label = sg.Text("Ref Obs Miss Flag:", size=MONITOR_LABEL_SIZE, font=label_font, justification=MONITOR_ALIGN)
        hdg_flags_hdgvalid_label = sg.Text("Heading Valid Flag:", size=MONITOR_LABEL_SIZE, font=label_font, justification=MONITOR_ALIGN)
        hdg_flags_normalized_label = sg.Text("Normalized Flag:", size=MONITOR_LABEL_SIZE, font=label_font, justification=MONITOR_ALIGN)
        hdg_flags_carrsoln_label = sg.Text("Carrier Solution Flag:", size=MONITOR_LABEL_SIZE, font=label_font, justification=MONITOR_ALIGN)

        hdg_row1 = [hdg_heading_label, hdg_heading_value, hdg_length_label, hdg_length_value]
        #hdg_flags_row = [hdg_flags_label, hdg_flags_value]
        hdg_row2 = [hdg_north_label, hdg_north_value, hdg_east_label, hdg_east_value]
        hdg_row3 = [hdg_down_label, hdg_down_value, hdg_flags_label, hdg_flags_value]
        hdg_row4 = [hdg_hdg_acc_label, hdg_hdg_acc_value, hdg_len_acc_label, hdg_len_acc_value]
        #flags
        hdg_row5 = [hdg_flags_fixok_label, hdg_flags_fixok_value, hdg_flags_diffsoln_label, hdg_flags_diffsoln_value]
        hdg_row6 = [hdg_flags_posvalid_label, hdg_flags_posvalid_value, hdg_flags_ismoving_label, hdg_flags_ismoving_value]
        hdg_row7 = [hdg_flags_refposmiss_label, hdg_flags_refposmiss_value, hdg_flags_refobsmiss_label, hdg_flags_refobsmiss_value]
        hdg_row8 = [hdg_flags_hdgvalid_label, hdg_flags_hdgvalid_value, hdg_flags_normalized_label, hdg_flags_normalized_value]
        hdg_row9 = [hdg_flags_carrsoln_label, hdg_flags_carrsoln_value]

        hdg_tab_layout = [hdg_row1, hdg_row4, hdg_row2, hdg_row3, hdg_row5, hdg_row6, hdg_row7, hdg_row8, hdg_row9]
        hdg_tab = sg.Tab(MONITOR_HDG_TAB_TITLE, hdg_tab_layout, key="hdg-tab")

        #________________TAB 6: Map display_______________________

        arrow_file_path = os.path.join("map", ARROW_FILE_NAME)  # needs path relative to this file, not geotiler_demo
        #MAP_INITIAL_SIZE = 200  # does this need a default?
        # image to hold geotiler map: create the element first and update it later
        try:
            map_image = sg.Image(DEFAULT_MAP_IMAGE, size=MAP_DIMENSIONS) #TODO - make it a constant, set the size too.
        except Exception as e:
            map_image = sg.Image() #(key="-IMAGE-")  # does it need the key?
        # bio = io.BytesIO() #for storing images, but doesn't update properly out here

        try:
            provider_credit_text_holder = sg.InputText("", disabled=True, expand_x=True, expand_y=True)# border_width, pad
        except Exception as e:
            provider_credit_text_holder = sg.InputText("", disabled=True)  #fallback if expand_x not recognized

        #map_main_column = sg.Column([[provider_credit_text_holder], [map_image]]) #credit text on top of map
        map_main_column = sg.Frame("",[[provider_credit_text_holder], [map_image]], #credit text on top of map
                                   relief=sg.RELIEF_RAISED, border_width=5)#, background_color="green")
        #try_set_expand(map_image)

        #put things on side of map: zoom in, zoom out, angle dials
        zoom_label = sg.Text("zoom:", size=(6,1), font=label_font)
        zoom_in_button = sg.Button(" + ", key="zoom_in_button",  enable_events=True, font=value_font)
        zoom_out_button = sg.Button("  - ", key="zoom_out_button", enable_events=True, font=value_font)

        map_side_frame = sg.Frame("", [
                                        [zoom_label], [zoom_out_button, zoom_in_button],
                                        ], element_justification='left',
                                        relief=sg.RELIEF_RAISED, border_width=5)
        map_side_column = sg.Column([[map_side_frame]], vertical_alignment='top')

        layout2 = [[map_main_column, map_side_column]]
        map_tab = sg.Tab(MONITOR_MAP_TAB_TITLE, layout2, key="map-tab", element_justification="top")#,title_color='Black', background_color='Orange', element_justification='right')

        #________________Window structure: contains both tabs_______________________

        tab_group = sg.TabGroup([[ins_tab, imu_tab, gps_tab, gp2_tab, hdg_tab, map_tab]])#, tab_location='top',  # top, topleft, bottom, bottomright, left, right
                                #title_color='Red', tab_background_color='White',  # non-selected tabs
                                #selected_title_color='Yellow', selected_background_color='Blue')  # selected tab
        try_set_expand(tab_group)

        #group elements by size for resizing  - can this be assembled from ins_fields, imu_fields etc?
        label_font_elements = [lat_label, lon_label, speed_label, att0_label, att1_label, att2_label,
                               soln_label, zupt_label, gps_carrsoln_label2, gps_fix_label2, alt_label, num_sats_label2,
                               ax_label, ay_label, az_label, wx_label, wy_label, wz_label, fog_label, temp_label, odo_label,

                               imu_time_label, imu_sync_label, ins_imu_time_label, ins_gps_time_label,

                               hdg_heading_label, hdg_length_label, hdg_flags_label,
                               hdg_north_label, hdg_east_label, hdg_down_label,
                               hdg_len_acc_label, hdg_hdg_acc_label,
                               hdg_flags_fixok_label, hdg_flags_diffsoln_label, hdg_flags_posvalid_label, hdg_flags_ismoving_label,
                               hdg_flags_refposmiss_label, hdg_flags_refobsmiss_label, hdg_flags_hdgvalid_label,
                               hdg_flags_normalized_label, hdg_flags_carrsoln_label,
                               
                               gps_lat_label, gps_lon_label, gps_elipsoid_label, gps_msl_label, gps_speed_label,
                               gps_heading_label, gps_hacc_label, gps_vacc_label, gps_pdop_label, gps_fix_label,
                               gps_numsv_label, gps_carrsoln_label, gps_spd_acc_label, gps_hdg_acc_label,

                               gp2_lat_label, gp2_lon_label, gp2_elipsoid_label, gp2_msl_label, gp2_speed_label,
                               gp2_heading_label, gp2_hacc_label, gp2_vacc_label, gp2_pdop_label, gp2_fix_label,
                               gp2_numsv_label, gp2_carrsoln_label, gp2_spd_acc_label, gp2_hdg_acc_label]

        value_font_elements = [lat, lon, speed, att0, att1, att2, soln, zupt, gps_carrsoln2, gps_fix2, alt_value, num_sats_value2,
                               ax_value, ay_value, az_value, wx_value, wy_value, wz_value, fog_value, temp_value, odo_value,

                               imu_time_value, imu_sync_value, ins_imu_time_value, ins_gps_time_value,

                               hdg_heading_value, hdg_length_value, hdg_flags_value,
                               hdg_north_value, hdg_east_value, hdg_down_value,
                               hdg_len_acc_value, hdg_hdg_acc_value,
                               hdg_flags_fixok_value, hdg_flags_diffsoln_value, hdg_flags_posvalid_value,
                               hdg_flags_ismoving_value,
                               hdg_flags_refposmiss_value, hdg_flags_refobsmiss_value, hdg_flags_hdgvalid_value,
                               hdg_flags_normalized_value, hdg_flags_carrsoln_value,

                               gps_lat_value, gps_lon_value, gps_elipsoid_value, gps_msl_value, gps_speed_value,
                               gps_heading_value, gps_hacc_value, gps_vacc_value, gps_pdop_value, gps_fix_value,
                               gps_numsv_value, gps_carrsoln_value, gps_spd_acc_value, gps_hdg_acc_value,

                               gp2_lat_value, gp2_lon_value, gp2_elipsoid_value, gp2_msl_value, gp2_speed_value,
                               gp2_heading_value, gp2_hacc_value, gp2_vacc_value, gp2_pdop_value, gp2_fix_value,
                               gp2_numsv_value, gp2_carrsoln_value, gp2_spd_acc_value, gp2_hdg_acc_value,
                               ]
        buttons = [gps_button, log_button]

        top_layout = [buttons_row, [sg.HSeparator()], [tab_group]] #buttons on top, then tab 1 or 2
        window = sg.Window(title="Output monitoring", layout=top_layout, finalize=True, resizable=True)
        #any updates on elements need to be after this "finalize=True" statement (or after window.read if not finalized)

        window.bind('<Configure>', "Configure")
        base_width, base_height = window.size
        debug_print("BASE_WIDTH: "+str(base_width))
        debug_print("BASE_HEIGHT:" +str(base_height))

        last_last_ins = b''
        last_last_gps = b''
        last_last_gp2 = b''
        last_last_imu = b''
        last_last_hdg = b''
        last_ins_time = time.time()
        last_gps_time = last_ins_time
        last_gp2_time = last_ins_time
        last_imu_time = last_ins_time
        last_hdg_time = last_ins_time

        #last_odo_speed = None
        last_odo_time = last_ins_time

        #fields by message type and tab, for zeroing out when no data.
        ins_fields = [lat, lon, speed, att0, att1, att2, soln, zupt, alt_value, ins_gps_time_value, ins_imu_time_value]
        imu_fields = [ax_value, ay_value, az_value, wx_value, wy_value, wz_value, fog_value, temp_value, imu_time_value, imu_sync_value]
        ins_tab_gps_fields = [gps_carrsoln2, gps_fix2, num_sats_value2]
        gps_tab_gps_fields = [gps_lat_value,gps_lon_value,gps_elipsoid_value,gps_msl_value,
                              gps_speed_value,gps_heading_value,
                              gps_hacc_value,gps_vacc_value,gps_pdop_value,
                              gps_fix_value,gps_numsv_value,gps_carrsoln_value,gps_spd_acc_value,gps_hdg_acc_value]
        gp2_tab_gp2_fields = [gp2_lat_value, gp2_lon_value, gp2_elipsoid_value, gp2_msl_value,
                              gp2_speed_value, gp2_heading_value,
                              gp2_hacc_value, gp2_vacc_value, gp2_pdop_value,
                              gp2_fix_value, gp2_numsv_value, gp2_carrsoln_value, gp2_spd_acc_value, gp2_hdg_acc_value]

        hdg_fields = [hdg_heading_value, hdg_length_value, hdg_flags_value]

        #hide tabs and text that don't apply for the product type.
        # Hiding is easier than removing since it allows updating the elements. updating a missing element will crash.
        if not self.show_gps_info:
            for clickable_item in [ins_tab, gps_tab, gp2_tab, hdg_tab, map_tab, gps_button]:
                clickable_item.update(visible=False, disabled=True)
            for text_item in [time_since_gps_label, time_since_gps, odo_label, odo_value]:
                text_item.update(visible=False) #text elements have no "disabled". could check if hasattr("disabled")

        ## JT - ADD ZMQ PUBLISHER
                
        context = zmq.Context()
        socket = context.socket(zmq.PUB)
        socket.bind("tcp://127.0.0.1:9004")
        topic = "anello"

        json_out = {"heading_imu": None, "heading_gnss": None, "lat1" : None, "lng1": None}

        # update loop: check for new messages or button clicks, then update the displayed data
        while True:
            if json_out["heading_imu"] is not None and json_out["lat1"] is not None and json_out["lng1"] is not None and json_out["heading_gnss"] is not None:
                socket.send_string(topic, zmq.SNDMORE)
                socket.send_json(json_out)

            event, values = window.read(timeout=MONITOR_REFRESH_MS, timeout_key="timeout")
            active_tab = tab_group.get() #check this early so it can update only the active tab
            if event != "timeout":
                debug_print("event: " + str(event))
                debug_print("values: " + str(values))

            if event == sg.WIN_CLOSED:  # close - return to wait_for_monitor_start
                window.close() #needs this to close properly on raspberry pi. not needed in windows.
                break
            elif event == "gps_button" and gps_working:
                #switch to opposite state
                if gps_is_on:
                    configs = {'gps1': b'off', 'gps2': b'off'}
                else:
                    configs = {'gps1': b'on', 'gps2': b'on'}
                write_resp = self.retry_command(method=self.board.set_cfg, args=[configs], response_types=[b'CFG']) #toggle gps in RAM only

                #read again to update button in case of failure
                read_resp = self.retry_command(method=self.board.get_cfg, args=[["gps1"]], response_types=[b'CFG'])
                gps_is_on = read_resp.configurations["gps1"] == b'on'
                gps_button.update(GPS_TEXT+TOGGLE_TEXT[gps_is_on], button_color=TOGGLE_COLORS[gps_is_on])
            elif event == "log_button":
                #stop if on, start if off
                if self.log_on.value:
                    self.stop_logging()
                else:
                    #start log with default name
                    logname = collector.default_log_name(self.serialnum)
                    self.log_name.value = logname.encode()
                    self.log_on.value = 1
                    self.log_start.value = 1
                #update color
                log_button.update(LOG_TEXT+TOGGLE_TEXT[self.log_on.value], button_color=TOGGLE_COLORS[self.log_on.value])
            elif event == "Configure": #resize, move. also triggers on button for some reason.
                debug_print("size:")
                debug_print(repr(window.size))
                width, height = window.size
                scale = min(width / base_width , height / base_height)
                for item in value_font_elements:
                    item.update(font=(FONT_NAME, int(VALUE_FONT_SIZE * scale)))
                for item in label_font_elements:
                    item.update(font=(FONT_NAME, int(LABEL_FONT_SIZE * scale)))
                for item in buttons:
                    item.font = (FONT_NAME, int(LABEL_FONT_SIZE * scale))
                #zupt.update(font = (FONT_NAME, int(VALUE_FONT_SIZE * scale)))
            #zoom in/out buttons -> update current zoom. TODO - refresh map with that zoom too?
            elif event == "zoom_in_button":
                current_zoom = min(current_zoom + 1, MAP_ZOOM_MAX)
                debug_print("map zoom = "+str(current_zoom))
            elif event == "zoom_out_button":
                current_zoom = max(current_zoom - 1, MAP_ZOOM_MIN)
                debug_print("map zoom = " + str(current_zoom))

            #update for new ins data , only update items in the active tab.
            if hasattr(self.last_ins_msg, "raw"):
                #print(f"has last_ins_msg: {self.last_ins_msg.raw}")
                #active_tab = tab_group.get() #move to top of loop
                elapsed = time.time() - last_ins_time
                # window["since_ins"].update('%.2f' % elapsed)
                #if self.last_ins_msg.value == last_last_ins:
                if self.last_ins_msg.raw == last_last_ins:
                    #did not change - no update. but if it's been too long, zero the fields
                    #time_since_ins.update(str(elapsed))
                    #window.refresh()
                    if (elapsed > ZERO_OUT_TIME) and active_tab == "numbers-tab": #zero out the numbers tab
                        for field in ins_fields:
                            field.update(MONITOR_DEFAULT_VALUE)
                else: #changed - update the last_ins and counter, then update display from the new values
                    #last_last_ins = self.last_ins_msg.value
                    last_last_ins = self.last_ins_msg.raw
                    last_ins_time = time.time()

                    ins_msg = try_multiple_parsers([binary_scheme, ascii_scheme, rtcm_scheme], self.last_ins_msg.raw)
                    #print(f"\nins_msg: {ins_msg}")

                    #Simple json for now. 
                    json_out["heading_gnss"] = ins_msg.heading_deg if hasattr(ins_msg, "heading_deg") else json_out["heading_gnss"] 
                    json_out["lat1"] = ins_msg.lat_deg if hasattr(ins_msg, "lat_deg") else json_out["lat1"]
                    json_out["lng1"] = ins_msg.lon_deg if hasattr(ins_msg, "lon_deg") else json_out["lng1"]


                    #update numbers display if active
                    if active_tab == "numbers-tab":
                        # debug_print(msg)
                        # for label, attrname in configs:
                        # textval = str(getattr(msg, attrname) if hasattr(msg, attrname) else default_value
                        # window[label].update(textval)
                        window["lat"].update('%.7f'%ins_msg.lat_deg if hasattr(ins_msg, "lat_deg") else MONITOR_DEFAULT_VALUE)
                        window["lon"].update('%.7f'%ins_msg.lon_deg if hasattr(ins_msg, "lon_deg") else MONITOR_DEFAULT_VALUE)

                        #compute ins speed as magnitude. include vz? should be small anyway
                        vx = float(ins_msg.velocity_north_mps) if hasattr(ins_msg, "velocity_north_mps") else 0
                        vy = float(ins_msg.velocity_east_mps) if hasattr(ins_msg, "velocity_east_mps") else 0
                        vz = float(ins_msg.velocity_down_mps) if hasattr(ins_msg, "velocity_down_mps") else 0
                        magnitude = ((vx**2)+(vy**2)+(vz**2))**(1/2)

                        window["speed"].update('%.3f'%magnitude)
                        window["att0"].update(
                            '%.1f'%ins_msg.roll_deg if hasattr(ins_msg, "roll_deg") else MONITOR_DEFAULT_VALUE)
                        window["att1"].update(
                            '%.1f'%ins_msg.pitch_deg if hasattr(ins_msg, "pitch_deg") else MONITOR_DEFAULT_VALUE)
                        window["att2"].update(
                            '%.1f'%ins_msg.heading_deg if hasattr(ins_msg, "heading_deg") else MONITOR_DEFAULT_VALUE)

                        window["soln"].update(INS_SOLN_NAMES.get(ins_msg.ins_solution_status, str(ins_msg.ins_solution_status))
                            if hasattr(ins_msg, "ins_solution_status") else MONITOR_DEFAULT_VALUE)

                        window["zupt"].update(ZUPT_NAMES.get(ins_msg.zupt_flag, str(ins_msg.zupt_flag))
                                              if hasattr(ins_msg, "zupt_flag") else MONITOR_DEFAULT_VALUE)

                        window["altitude"].update('%.1f'%ins_msg.alt_m if hasattr(ins_msg, "alt_m") else MONITOR_DEFAULT_VALUE)

                        window["ins_imu_time"].update(
                            '%.1f' % ins_msg.imu_time_ms if hasattr(ins_msg, "imu_time_ms") else MONITOR_DEFAULT_VALUE)

                        window["ins_gps_time"].update(
                            '%d' % ins_msg.gps_time_ns if hasattr(ins_msg, "gps_time_ns") else MONITOR_DEFAULT_VALUE)

                    #Update Map if active
                    if active_tab == "map-tab":
                        #credit the provider selected with some text - maps from: name, website, copyright/license terms

                        provider = "osm"  # force "osm" for now since stamen not working in geotiler.
                        provider_credit_text = MAP_PROVIDER_CREDITS[provider] if provider in MAP_PROVIDER_CREDITS \
                            else "maps from " + str(provider) + ", needs copyright/license info adding here"
                        provider_credit_text_holder.update(provider_credit_text)

                        #from ins message - could share variable with text updates above
                        lat = ins_msg.lat_deg if hasattr(ins_msg, "lat_deg") else None #if None, will not update
                        lon = ins_msg.lon_deg if hasattr(ins_msg, "lon_deg") else None
                        heading = ins_msg.heading_deg if hasattr(ins_msg, "heading_deg") else None #0,1,2 = roll, pitch, heading

                        #update the map, only if the lat/lon/position all received
                        if (lat is not None) and (lon is not None) and (heading is not None):
                            #tried to suppress map error prints with no internet, but doesn't work.
                            #with open(os.devnull, "w") as f, redirect_stdout(f):
                            pil_image = draw_map(lat, lon, current_zoom, MAP_DIMENSIONS, MAP_ARROW_SIZE, heading, arrow_file_path, provider, storage=self.map_cache)
                            bio = io.BytesIO()  # todo- does this accumulate memory? but if bio outside loop, image does't update
                            pil_image.save(bio, format="PNG")  # put it in memory to load
                            map_image.update(data=bio.getvalue()) #todo - check actual window size and handle resizes?

                # window.refresh()
            if hasattr(self.last_gps_msg, "raw"):
                #print(f"has last_gps_msg: {self.last_gps_msg.raw}")
                elapsed = time.time() - last_gps_time
                window["since_gps"].update('%.2f' % elapsed) #outside of tabs, do it whichever tab is active
                #if self.last_gps_msg.value == last_last_gps:
                if self.last_gps_msg.raw == last_last_gps:
                    #did not change - no update. but if it's been too long, zero the fields
                    # time_since_gps.update(str(elapsed))
                    # window.refresh()
                    if elapsed > ZERO_OUT_TIME:
                        if active_tab == "numbers-tab": #zero these if tab is active
                            for field in ins_tab_gps_fields:
                                field.update(MONITOR_DEFAULT_VALUE)
                        elif active_tab == "gps-tab":
                            for field in gps_tab_gps_fields:
                                field.update(MONITOR_DEFAULT_VALUE)
                else:
                    #last_last_gps = self.last_gps_msg.value
                    last_last_gps = self.last_gps_msg.raw
                    last_gps_time = time.time()
                    if active_tab == 'numbers-tab': #these items are in numbers tab, so update only if active
                        gps_msg = try_multiple_parsers([binary_scheme, ascii_scheme, rtcm_scheme], self.last_gps_msg.raw)
                        #print(f"\ngps_msg: {gps_msg}")
                        window["gps_carrsoln2"].update(GPS_SOLN_NAMES.get(gps_msg.carrier_solution_status, str(gps_msg.carrier_solution_status))
                                                      if hasattr(gps_msg, "carrier_solution_status") else MONITOR_DEFAULT_VALUE)
                        window["gps_fix2"].update(GPS_FIX_NAMES.get(gps_msg.gnss_fix_type, str(gps_msg.gnss_fix_type))
                                                 if hasattr(gps_msg, "gnss_fix_type") else MONITOR_DEFAULT_VALUE)
                        window["num_sats2"].update(gps_msg.num_sats if hasattr(gps_msg, "num_sats") else MONITOR_DEFAULT_VALUE)
                    if active_tab == 'gps-tab':
                        gps_msg = try_multiple_parsers([binary_scheme, ascii_scheme, rtcm_scheme], self.last_gps_msg.raw)
                        #update the fields. todo: can this be a loop over gps_tab_gps_fields?
                        window["gps_lat"].update('%.7f' % gps_msg.lat_deg if hasattr(gps_msg, "lat_deg") else MONITOR_DEFAULT_VALUE)
                        window["gps_lon"].update('%.7f' % gps_msg.lon_deg if hasattr(gps_msg, "lon_deg") else MONITOR_DEFAULT_VALUE)
                        window["gps_alt_ell"].update('%.2f' % gps_msg.alt_ellipsoid_m if hasattr(gps_msg, "alt_ellipsoid_m") else MONITOR_DEFAULT_VALUE)
                        window["gps_alt_msl"].update('%.2f' % gps_msg.alt_msl_m if hasattr(gps_msg, "alt_msl_m") else MONITOR_DEFAULT_VALUE)
                        window["gps_spd"].update('%.2f' % gps_msg.speed_mps if hasattr(gps_msg, "speed_mps") else MONITOR_DEFAULT_VALUE)
                        window["gps_hdg"].update('%.2f' % gps_msg.heading_deg if hasattr(gps_msg, "heading_deg") else MONITOR_DEFAULT_VALUE)
                        window["gps_hacc"].update('%.2f' % gps_msg.accuracy_horizontal_m if hasattr(gps_msg, "accuracy_horizontal_m") else MONITOR_DEFAULT_VALUE)
                        window["gps_vacc"].update('%.2f' % gps_msg.accuracy_vertical_m if hasattr(gps_msg, "accuracy_vertical_m") else MONITOR_DEFAULT_VALUE)
                        window["gps_pdop"].update('%.2f' % gps_msg.PDOP if hasattr(gps_msg, "PDOP") else MONITOR_DEFAULT_VALUE)
                        window["gps_numsv"].update(gps_msg.num_sats if hasattr(gps_msg, "num_sats") else MONITOR_DEFAULT_VALUE) #int, don't %3f.
                        window["gps_spd_acc"].update('%.2f' % gps_msg.speed_accuracy_mps if hasattr(gps_msg, "speed_accuracy_mps") else MONITOR_DEFAULT_VALUE)
                        window["gps_hdg_acc"].update('%.2f' % gps_msg.heading_accuracy_deg if hasattr(gps_msg, "heading_accuracy_deg") else MONITOR_DEFAULT_VALUE)
                        #values with names - get name from dictionary.
                        window["gps_carrsoln"].update(GPS_SOLN_NAMES.get(gps_msg.carrier_solution_status, str(gps_msg.carrier_solution_status))
                                                      if hasattr(gps_msg, "carrier_solution_status") else MONITOR_DEFAULT_VALUE)
                        window["gps_fix"].update(GPS_FIX_NAMES.get(gps_msg.gnss_fix_type, str(gps_msg.gnss_fix_type))
                                                 if hasattr(gps_msg, "gnss_fix_type") else MONITOR_DEFAULT_VALUE)

            #update GP2 tab for GP2 message. TODO - can this logic be combined with GPS tab?
            if hasattr(self.last_gp2_msg, "raw"):
                #print(f"has last_gps_msg: {self.last_gps_msg.raw}")
                elapsed = time.time() - last_gp2_time
                if self.last_gp2_msg.raw == last_last_gp2:
                    #did not change - no update. but if it's been too long, zero the fields
                    if elapsed > ZERO_OUT_TIME:
                        if active_tab == "gp2-tab":
                            for field in gp2_tab_gp2_fields:
                                field.update(MONITOR_DEFAULT_VALUE)
                else:
                    #last_last_gps = self.last_gps_msg.value
                    last_last_gp2 = self.last_gp2_msg.raw
                    last_gp2_time = time.time()
                    if active_tab == 'gp2-tab':
                        gps_msg = try_multiple_parsers([binary_scheme, ascii_scheme, rtcm_scheme], self.last_gp2_msg.raw)
                        #update the fields. todo: can this be a loop over gps_tab_gps_fields?
                        window["gp2_lat"].update('%.7f' % gps_msg.lat_deg if hasattr(gps_msg, "lat_deg") else MONITOR_DEFAULT_VALUE)
                        window["gp2_lon"].update('%.7f' % gps_msg.lon_deg if hasattr(gps_msg, "lon_deg") else MONITOR_DEFAULT_VALUE)
                        window["gp2_alt_ell"].update('%.2f' % gps_msg.alt_ellipsoid_m if hasattr(gps_msg, "alt_ellipsoid_m") else MONITOR_DEFAULT_VALUE)
                        window["gp2_alt_msl"].update('%.2f' % gps_msg.alt_msl_m if hasattr(gps_msg, "alt_msl_m") else MONITOR_DEFAULT_VALUE)
                        window["gp2_spd"].update('%.2f' % gps_msg.speed_mps if hasattr(gps_msg, "speed_mps") else MONITOR_DEFAULT_VALUE)
                        window["gp2_hdg"].update('%.2f' % gps_msg.heading_deg if hasattr(gps_msg, "heading_deg") else MONITOR_DEFAULT_VALUE)
                        window["gp2_hacc"].update('%.2f' % gps_msg.accuracy_horizontal_m if hasattr(gps_msg, "accuracy_horizontal_m") else MONITOR_DEFAULT_VALUE)
                        window["gp2_vacc"].update('%.2f' % gps_msg.accuracy_vertical_m if hasattr(gps_msg, "accuracy_vertical_m") else MONITOR_DEFAULT_VALUE)
                        window["gp2_pdop"].update('%.2f' % gps_msg.PDOP if hasattr(gps_msg, "PDOP") else MONITOR_DEFAULT_VALUE)
                        window["gp2_numsv"].update(gps_msg.num_sats if hasattr(gps_msg, "num_sats") else MONITOR_DEFAULT_VALUE) #int, don't %3f.
                        window["gp2_spd_acc"].update('%.2f' % gps_msg.speed_accuracy_mps if hasattr(gps_msg, "speed_accuracy_mps") else MONITOR_DEFAULT_VALUE)
                        window["gp2_hdg_acc"].update('%.2f' % gps_msg.heading_accuracy_deg if hasattr(gps_msg, "heading_accuracy_deg") else MONITOR_DEFAULT_VALUE)
                        #values with names - get name from dictionary.
                        window["gp2_carrsoln"].update(GPS_SOLN_NAMES.get(gps_msg.carrier_solution_status, str(gps_msg.carrier_solution_status))
                                                      if hasattr(gps_msg, "carrier_solution_status") else MONITOR_DEFAULT_VALUE)
                        window["gp2_fix"].update(GPS_FIX_NAMES.get(gps_msg.gnss_fix_type, str(gps_msg.gnss_fix_type))
                                                 if hasattr(gps_msg, "gnss_fix_type") else MONITOR_DEFAULT_VALUE)
            if hasattr(self.last_imu_msg, "raw"):
                #print(f"has last_imu_msg: {self.last_imu_msg.raw}")
                #update for new imu message
                elapsed = time.time() - last_imu_time
                #TODO - can update any "time since imu" indicator here
                #if self.last_imu_msg.value == last_last_imu:
                if self.last_imu_msg.raw == last_last_imu:
                    # did not change - no update. but if it's been too long, zero the fields
                    # time_since_ins.update(str(elapsed))
                    # window.refresh()
                    if (elapsed > ZERO_OUT_TIME) and active_tab == "imu-tab":  # zero out the numbers tab
                        for field in imu_fields:
                            field.update(MONITOR_DEFAULT_VALUE)
                else:  # changed - update the last_ins and counter, then update display from the new values
                    # last_last_imu = self.last_imu_msg.value
                    last_last_imu = self.last_imu_msg.raw
                    last_imu_time = time.time()
                    imu_msg = try_multiple_parsers([binary_scheme, ascii_scheme, rtcm_scheme], self.last_imu_msg.raw)
                    if active_tab == 'imu-tab':
                        #print(f"\nimu_msg: {imu_msg}")
                        #update the imu fields from the message
                        window["ax_value"].update('%.4f'%imu_msg.accel_x_g if hasattr(imu_msg, "accel_x_g")
                                                  else MONITOR_DEFAULT_VALUE)
                        window["ay_value"].update('%.4f' % imu_msg.accel_y_g if hasattr(imu_msg, "accel_y_g")
                                                  else MONITOR_DEFAULT_VALUE)
                        window["az_value"].update('%.4f' % imu_msg.accel_z_g if hasattr(imu_msg, "accel_z_g")
                                                  else MONITOR_DEFAULT_VALUE)
                        window["wx_value"].update('%.4f' % imu_msg.angrate_x_dps if hasattr(imu_msg, "angrate_x_dps")
                                                  else MONITOR_DEFAULT_VALUE)
                        window["wy_value"].update('%.4f' % imu_msg.angrate_y_dps if hasattr(imu_msg, "angrate_y_dps")
                                                  else MONITOR_DEFAULT_VALUE)
                        window["wz_value"].update('%.4f' % imu_msg.angrate_z_dps if hasattr(imu_msg, "angrate_z_dps")
                                                  else MONITOR_DEFAULT_VALUE)
                        window["fog_value"].update('%.4f' % imu_msg.fog_angrate_z_dps
                                                   if hasattr(imu_msg, "fog_angrate_z_dps") else MONITOR_DEFAULT_VALUE)
                        window["temp_value"].update('%.2f' % imu_msg.temperature_c
                                                   if hasattr(imu_msg, "temperature_c") else MONITOR_DEFAULT_VALUE)
                        window["imu_cpu_time"].update('%.2f' % imu_msg.imu_time_ms
                                                    if hasattr(imu_msg, "imu_time_ms") else MONITOR_DEFAULT_VALUE)
                        window["imu_sync_time"].update('%.2f' % imu_msg.sync_time_ms
                                                    if hasattr(imu_msg, "sync_time_ms") else MONITOR_DEFAULT_VALUE)

                        #message with an odometer speed/time: update the latest speed, reset timer.
                        if hasattr(imu_msg, "odometer_speed_mps") and hasattr(imu_msg, "odometer_time_ms") and imu_msg.odometer_time_ms > 0:
                            #odo_value =  '%.2f' % imu_msg.odometer_speed_mps
                            #last_odo_speed = imu_msg.odometer_speed_mps
                            last_odo_time = time.time() #or use time of the message?
                            window["odo_value"].update('%.2f' % imu_msg.odometer_speed_mps)
                        #if timer runs out, blank the odo speed.
                        elif time.time() - last_odo_time > ODOMETER_ZERO_TIME:
                            #odo_value = MONITOR_DEFAULT_VALUE #TODO - do the timeout logic here.
                            window["odo_value"].update(MONITOR_DEFAULT_VALUE)
            if hasattr(self.last_hdg_msg, "raw"):
                #print(f"last_hdg_msg.raw is {self.last_hdg_msg.raw}")
                elapsed_hdg = time.time() - last_hdg_time
                # can update any "time since hdg" indicator here
                if self.last_hdg_msg.raw == last_last_hdg:
                    # can zero any heading fields if too much time passed
                    if (elapsed_hdg > ZERO_OUT_TIME) and active_tab == "gps-tab":  # zero out the numbers tab
                        for field in hdg_fields:
                            field.update(MONITOR_DEFAULT_VALUE)
                else:  # changed - update the last_ins and counter, then update display from the new values
                    # last_last_imu = self.last_imu_msg.value
                    last_last_hdg = self.last_hdg_msg.raw
                    last_hdg_time = time.time()
                    json_out["heading_imu"] = ins_msg.heading_deg if hasattr(ins_msg, "relPosHeading_deg") else json_out["heading_imu"] 

                    if active_tab == 'hdg-tab':
                        hdg_msg = try_multiple_parsers([binary_scheme, ascii_scheme, rtcm_scheme], self.last_hdg_msg.raw)
                        #print(f"new heading message: {hdg_msg}")
                        #update the hdg monitor fields here
                        window["hdg_hdg"].update('%.2f' % hdg_msg.relPosHeading_deg if hasattr(hdg_msg, "relPosHeading_deg")
                                                  else MONITOR_DEFAULT_VALUE)
                        window["hdg_len"].update('%.2f' % hdg_msg.relPosLen_m if hasattr(hdg_msg, "relPosLen_m")
                                                  else MONITOR_DEFAULT_VALUE)

                        window["hdg_N"].update('%.2f' % hdg_msg.relPosN_m if hasattr(hdg_msg, "relPosN_m")
                                                  else MONITOR_DEFAULT_VALUE)
                        window["hdg_E"].update('%.2f' % hdg_msg.relPosE_m if hasattr(hdg_msg, "relPosE_m")
                                                  else MONITOR_DEFAULT_VALUE)
                        window["hdg_D"].update('%.2f' % hdg_msg.relPosD_m if hasattr(hdg_msg, "relPosD_m")
                                                  else MONITOR_DEFAULT_VALUE)
                        window["hdg_lenacc"].update('%.2f' % hdg_msg.relPosLenAcc_m if hasattr(hdg_msg, "relPosLenAcc_m")
                                                  else MONITOR_DEFAULT_VALUE)
                        window["hdg_hdgacc"].update('%.2f' % hdg_msg.relPosHeadingAcc_deg if hasattr(hdg_msg, "relPosHeadingAcc_deg")
                                                  else MONITOR_DEFAULT_VALUE)
                        window["hdg_flags"].update(hdg_msg.flags if hasattr(hdg_msg, "flags") #int, don't show decimals
                                                  else MONITOR_DEFAULT_VALUE)
                        #flags are ints - show as 1/0 or on/off?
                        window["hdg_flags_fixok"].update(hdg_msg.gnssFixOK if hasattr(hdg_msg, "gnssFixOK")
                                                  else MONITOR_DEFAULT_VALUE)
                        window["hdg_flags_diffsoln"].update(hdg_msg.diffSoln if hasattr(hdg_msg, "diffSoln")
                                                  else MONITOR_DEFAULT_VALUE)
                        window["hdg_flags_posvalid"].update(hdg_msg.relPosValid if hasattr(hdg_msg, "relPosValid")
                                                  else MONITOR_DEFAULT_VALUE)
                        window["hdg_flags_ismoving"].update(hdg_msg.isMoving if hasattr(hdg_msg, "isMoving")
                                                  else MONITOR_DEFAULT_VALUE)
                        window["hdg_flags_refposmiss"].update(hdg_msg.refPosMiss if hasattr(hdg_msg, "refPosMiss")
                                                  else MONITOR_DEFAULT_VALUE)
                        window["hdg_flags_refobsmiss"].update(hdg_msg.refObsMiss if hasattr(hdg_msg, "refObsMiss")
                                                  else MONITOR_DEFAULT_VALUE)
                        window["hdg_flags_hdgvalid"].update(hdg_msg.relPosHeading_Valid if hasattr(hdg_msg, "relPosHeading_Valid")
                                                  else MONITOR_DEFAULT_VALUE)
                        window["hdg_flags_normalized"].update(hdg_msg.relPos_Normalized if hasattr(hdg_msg, "relPos_Normalized")
                                                  else MONITOR_DEFAULT_VALUE)
                        window["hdg_flags_carrsoln"].update(hdg_msg.carrSoln if hasattr(hdg_msg, "carrSoln")
                                                  else MONITOR_DEFAULT_VALUE)

    # tell them to get bootloader exe and hex, give upgrade instructions. Will not do this automatically yet.
    # prompt to activate boot loader mode
    def upgrade(self):
        print("\nFirmware upgrade process")
        print("\nNotes:")
        print("\tGet the firmware file from Anello Photonics: IMU-A1_v<version number>.hex")
        print("\tSoftware update is over USB only, not ethernet.")
        print("\tRequires Windows OS.")

        # check for windows, connected over usb
        if os.name != 'nt':
            show_and_pause("\nBootloader currently works on Windows only.")
            return

        if not (self.board and self.connection_info["type"] == "COM"):
            show_and_pause("\nMust connect by USB before upgrading (not over ethernet)")

            return

        print("\nSelect the firmware file")
        hex_files_only_option = [("hex files", ".hex")]  # only allows picking .hex file.
        hex_file_path = pick_one_file(initialdir=None,
                                      title="Select hex file to load: IMU-A1_<version>.hex",
                                      filetypes=hex_files_only_option)
        if not hex_file_path: #on cancel, askopenfilename returns ""
            show_and_pause("\nfile not selected")
            return  # cancel the upgrade. TODO - should it open file picker again?
        hex_file_location, hex_file_name = os.path.split(hex_file_path) #or use os.path.basename, dirname

        print(f"\nSelected {hex_file_name}. Upgrade now?")
        options = ["Yes", "No"]
        if options[cutie.select(options)] == "Yes":
            self.release_for_bootload() #release data port and stop functions that use it like logging, ntrip
            try:
                expect_version_after = "unknown"  # this means it won't check expected version
                self.board.bootload_with_file_path(hex_file_path, expect_version_after, num_attempts=1)
            except Exception as e:
                print(f"\nError during firmware upgrade: {type(e)}: {e}\n")
                traceback.print_exc()
                show_and_pause("\nTry cycling power on unit and connect again. If it doesn't start up, contact Anello Photonics")
                return #should it try to connect here?

            show_and_pause(f"\n\nFinished updating")
            self.connect()  # go back to connect step since it disconnects during bootload.

        else:
            return

    # send regular reset, not bootloading reset
    def reset(self):
        if self.board:
            print("\nrestarting")
            self.board.reset_with_waits() #reset, then wait and ping until responsive.
        else:
            show_and_pause("must connect to unit before resetting")

    def plot(self):
        show_and_pause("Not implemented yet")

    # retry command on error responses (APERR type)
    # retry only on error codes from connection issues: no start, incomplete, checksum fail
    # don't retry on invalid field, invalid value which could happen from bad user input
    # method: the function to call. args: list of arguments
    def retry_command(self, method, response_types, args=[], retries=6):
        connection_errors = [1, 3, 4]
        #may need to clear input buffer here so some old message isn't read as a response.
        self.board.control_connection.reset_input_buffer() #TODO - make this actually do something for UDP
        for i in range(retries):
            try:
                output_msg = method(*args)
                # no response: retry
                if not output_msg:
                    continue
                # connection errors: retry. content errors like invalid fields/values don't retry
                if output_msg.msgtype == b'ERR' and output_msg.msgtype in connection_errors:
                    continue
                # invalid response message or unexpected response type: retry
                if not proper_response(output_msg, response_types):
                    continue
                else:
                    return output_msg
            except Exception as e:
                continue #error - treat as fail, retry
        #raise Exception("retry method: " + str(method) + " failed")
        # if it failed after retries, there is a connection problem
        if DEBUG:
            print(f"error in function {method.__name__}, types={response_types}, args = {args}")
        return None #didn't work -> function that calls this should check for None
        #self.release()
        #show_and_pause("connection error - check cables and reconnect")


#try setting expandable for a pysimplegui object - needs updated pysimplegui
def try_set_expand(gui_object, x=True, y=True):
    try:
        gui_object.expand_x = x
        gui_object.expand_y = y
    except Exception as e: #will happen on old PySimpleGUI that doesn't support expand, or wrong object type
        print(f"error setting expand on {gui_object}: {e}")


def version_greater_or_equal(our_ver, compareto):

    # chop any letters from front of our_ver, so we can compare by number
    for i in range(len(our_ver)):
        if our_ver[0].isalpha():
            our_ver = our_ver[1:]
        else:
            break

    try:
        our_nums = [int(c) for c in our_ver.split(".")]
        other_nums = [int(c) for c in compareto.split(".")]
    except Exception:
        return False #default False which will usually mean feature does not exist
    #compare from most important -> least important digit
    for i in range(3):
        if our_nums[i] > other_nums[i]:
            return True
        elif our_nums[i] < other_nums[i]:
            return False
    return True #equal

#try parsing a message by multiple parsers, return result of whichever worked (valid)
def try_multiple_parsers(parser_list, raw_data):
    for parser in parser_list:
        message = parser.parse_message(raw_data)
        #print(f"\n{type(parser)} parses: {message}")
        if message.valid:
            return message
    return None #fail, no parsers worked


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


def proper_response(message, expected_types): #UserProgram
    if not message:
        return False
    if not message.valid:  # actual problem with the message format or checksum fail, don't expect this
        print("\nMessage parsing error: "+message.error)
        return False
    elif message.msgtype in expected_types:
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


# prompt to form aln config from 3 angles into one string
# TODO - check what angle range to allow for these
def form_aln_string_prompt():
    roll_angle = cutie.get_number(prompt="roll adjustment (degrees): ", min_value=-360, max_value=360, allow_float=True)
    pitch_angle = cutie.get_number(prompt="pitch adjustment (degrees): ", min_value=-360, max_value=360, allow_float=True)
    heading_angle = cutie.get_number(prompt="heading adjustment (degrees): ", min_value=-360, max_value=360, allow_float=True)
    return f"{roll_angle:+.6f}{pitch_angle:+.6f}{heading_angle:+.6f}"


#(data_connection, logging_on, log_name, log_file, ntrip_on, ntrip_reader, ntrip_request, ntrip_ip, ntrip_port)
def runUserProg(exitflag, con_on, con_start, con_stop, con_succeed,
                con_type, com_port, com_baud, udp_ip, udp_port, gps_received,
                log_on, log_start, log_stop, log_name,
                ntrip_on, ntrip_start, ntrip_stop, ntrip_succeed,
                ntrip_ip, ntrip_port, ntrip_gga, ntrip_req,
                last_ins_msg, last_gps_msg, last_gp2_msg, last_imu_msg, last_hdg_msg,
                last_imu_time,
                serial_number
    ):
    prog = UserProgram(exitflag, con_on, con_start, con_stop, con_succeed,
                       con_type, com_port, com_baud, udp_ip, udp_port, gps_received,
                       log_on, log_start, log_stop, log_name,
                       ntrip_on, ntrip_start, ntrip_stop, ntrip_succeed,
                       ntrip_ip, ntrip_port, ntrip_gga, ntrip_req,
                       last_ins_msg, last_gps_msg, last_gp2_msg, last_imu_msg, last_hdg_msg,
                       last_imu_time,
                       serial_number
    )
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

    #shared vars for monitor
    last_ins_msg = Array('c', string_size)
    last_gps_msg = Array('c', string_size)
    last_gp2_msg = Array('c', string_size)
    last_imu_msg = Array('c', string_size)
    last_hdg_msg = Array('c', string_size)

    last_imu_time = Value('d', 0)

    serial_number = Array('c', string_size)

    shared_args = (exitflag, con_on, con_start, con_stop, con_succeed,
                   con_type, com_port, com_baud, udp_ip, udp_port, gps_received,
                   log_on, log_start, log_stop, log_name,
                   ntrip_on, ntrip_start, ntrip_stop, ntrip_succeed, ntrip_ip, ntrip_port, ntrip_gga, ntrip_req,
                   last_ins_msg, last_gps_msg, last_gp2_msg, last_imu_msg, last_hdg_msg,
                   last_imu_time,
                   serial_number              
    )
    io_process = Process(target=io_loop, args=shared_args)
    io_process.start()
    runUserProg(*shared_args) # must do this in main thread so it can take inputs
    io_process.join()

