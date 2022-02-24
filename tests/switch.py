#!/usr/bin/python
import threading
import socket
import time
import os
from datetime import datetime
import sys
import requests
import json


class Switch(): 

     # Switches class. it is a container for the different power switches
    __ON = "ON"
    __OFF = "OFF"
    def __init__(self, switch_model, switch_port, switch_ip, rebooting_sleep):
        self.__switch_port = switch_port
        self.__switch_model= switch_model
        self.__switch_ip = switch_ip
        self.__rebooting_sleep = rebooting_sleep

    def reset_board(self): # it does the power cycle on the board
        self.off()
        time.sleep(1)
        self.on()
        time.sleep(self.__rebooting_sleep)

    

    def on(self):
        self.__select_command_on_switch(self.__ON) #turns the configured power outlet on

    def off(self):
        self.__select_command_on_switch(self.__OFF) #turns the configured power outlet off

    def __select_command_on_switch(self, status): #calls the specific message formating and message sending method, depending on the selected power switch
        if self.__switch_model == "ip_power":
            self.__common_switch_command(status)
        elif self.__switch_model == "lindy":
            self.__lindy_switch(status)
        elif self.__switch_model == "debug":
            self.__debug_switch(status)
        else:
            raise ValueError("Incorrect switch switch_model")

    def __lindy_switch(self, status): # method for the lindy power switch, where it creates the message for turning on or off the power outlet
        to_change = "000000000000000000000000"
        led = f"{to_change[:(self.__switch_port - 1)]}1{to_change[self.__switch_port:]}"

        if status == self.__ON:
            url = f'http://{self.__switch_ip}/ons.cgi?led={led}'
        else:
            url = f'http://{self.__switch_ip}/offs.cgi?led={led}'
        payload = {
            "led": led,
        }
        headers = {
            "Host": self.__switch_ip,
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.12; rv:56.0) Gecko/20100101 Firefox/56.0",
            "Accept": "*/*",
            "Accept-Language": "en-US,en;q=0.5",
            "Accept-Encoding": "gzip, deflate",
            "Referer": f"http://{self.__switch_ip}/outlet.htm",
            "Authorization": "Basic c25tcDoxMjM0",
            "Connection": "keep-alive",
            "Content-Length": "0",
        }
        requests_status = requests.post(url, data=json.dumps(payload), headers=headers)

    def __common_switch_command(self, status):# method for the ip power power switch, where it creates the message for turning on or off the power outlet
        port_default_cmd = 'pw%1dName=&P6%1d=%%s&P6%1d_TS=&P6%1d_TC=&' % (
            self.__switch_port, self.__switch_port - 1, self.__switch_port - 1, self.__switch_port - 1)

        cmd = 'curl --data \"'
        cmd += port_default_cmd % ("On" if status == self.__ON else "Off")
        cmd += '&Apply=Apply\" '
        cmd += f'http://%s/tgi/iocontrol.tgi {self.__switch_ip}'
        cmd += '-o /dev/null 2>/dev/null'
        os.system(cmd)
        
    def __debug_switch(self, status): # dummy power switch, used for off-beam setup testing
        return



#s = Switch("192.168.1.100", 4)
#print "Port 1"
#s.cmd(int(1), 'On')
#s.cmd(int(1), 'Off')
#print "Port 2"


