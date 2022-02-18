#!/usr/bin/python3
import logging
import yaml
import zmq
import time
from classes.LoggerFormatter import ColoredLogger
from telnetlib import Telnet
from __future__ import print_function

from array import *
import binascii
from datetime import datetime
import io
import os
import re
import smtplib
import struct
from subprocess import Popen
import sys
import time
from time import sleep
import subprocess
import switch
import telnetlib
import time
import socket
import fcntl
import struct
import errno

DATA_SIZE=1

def write_logs(log_outf,str):
    print(str, end = "\n")
    log_outf.write(str+"\n")
    log_outf.flush()
    return
#getTime: returns a string representing the current time


def openLog(filename):

    date=getTime()
    log_outf = open(filename, "a")
    write_logs(getTime() +" " +board_ip +" [INFO] starting radiation experiment...")
    return log_outf

def read_message_data():
    #TODO: message reading function

#def logging_setup(logger_name, log_file):
    """
    Logging setup
    :return: logger
    """
    # create logger with 'spam_application'
#    logger = logging.getLogger(logger_name)
#    logger.setLevel(logging.DEBUG)
    # create file handler which logs even debug messages
#    fh = logging.FileHandler(log_file, mode='a')
#    fh.setLevel(logging.INFO)
    # create formatter and add it to the handlers
 #   file_formatter = logging.Formatter(fmt='%(asctime)s %(name)s %(levelname)s %(message)s %(filename)s:%(lineno)d',
#                                       datefmt='%d-%m-%y %H:%M:%S')

    # add the handlers to the logger
  #  fh.setFormatter(file_formatter)
   # logger.addHandler(fh)

    # create console handler with a higher log level for console
    #console = ColoredLogger(logger_name)
    ## noinspection PyTypeChecker
    #logger.addHandler(console)
    #return logger

def create_udp_socket(dut_ip,server_port)
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM) # the UDP socket which receives the messages
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind((get_self_ip_address(dut_ip), server_port))
    sock.settimeout(SOCKET_TIMEOUT) 
    return sock

#TODO this main receives the DUT ip, receving port, switch etc from an upper script which creates several diferent scripts
def main():
    """
    Main function
    :return: None
    """


    power_switch = switch.Switch(switch_type,switch_port,switch_ip, sleep_time)   #creates a power switch object
    server_socket=create_udp_socket(dut_ip,server_receiving_port);
    openLog(filename)
    # log format
    #logger = logging_setup(logger_name=__name__, log_file="server.log")

    # load yaml file
    #with open("server_parameters.yaml", 'r') as fp:
        #server_parameters = yaml.load(fp, Loader=yaml.SafeLoader)

    # attach signal handler for CTRL + C
    while True:
        try:
            data, addr = sock.recvfrom(DATA_SIZE)
        except socket.timeout:
            #TODO: how to handle timeout 
            #separate AppCrash from Linux Crash?
        except KeyboardInterrupt:
            logger.error("KeyboardInterrupt detected, exiting gracefully!( at least trying :) )")
            exit(130)
        #TODO: add other forms of ending the script

#TODO: control several different scripts
if __name__ == '__main__':
    main()
