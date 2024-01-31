# version number for user_program and other tools
PROGRAM_VERSION = 1.2

# ________________VERSION NOTES____________________

# _____ V1.2: updates to support firmware v1.2 release _____

#   new configurations in 1.2:
#       alignment: fine adjustment of x,y,z angles in degrees
#   configs added after user_program v1.1, but before v1.2:
#       PTP mode (off / slave / master) - for GNSS product only
#       nmea GGA output (on/off) : optional GGA message output
#       antenna baseline and baseline configuration: vehicle configs for dual antenna heading

#   support new binary output format, with smaller messages than RTCM format
#       output formats are now:  ASCII, RTCM, Binary
#       handle the Binary format in monitor window and CSV export

#   vehicle configs page: improve the status and warning text

#   Firmware update:
#       call the bootloader automatically so user doesn't have to paste commands in terminal.
#       add bootloader version 2 exe for IMU+. user_program will pick the bootloader based on product type.

#   fix bugs:
#       fix the flood of NTRIP data when coming back onto network, which can cause errors in GPS module or ethernet
#       hide strange prints which happened in python dependency imports and file pickers.


# _____ V1.1: updates to support with firmware v1.1 release _____

#   support new configurations in v1.1 firmware:
# 	    serial output on/off
# 	    ethernet output on/off
# 	    NTRIP channel serial/ethernet/off
# 	    time sync on/off
# 	    acceleration low pass filter (Hz)
# 	    MEMS gyro low pass filter (Hz)
# 	    optical gyro low pass filter (Hz)
# 	    output message format RTCM/ASCII
#
#   support RTCM message format in monitor and csv export
#
#   add new tabs in monitor for each message type (INS/IMU/GPS/GP2/HDG)
#
#   add monitor map tab - requires GPS signal and internet connection
#
#   add GP2 and HDG messages to csv export
#
#   various improvements and bug fixes
