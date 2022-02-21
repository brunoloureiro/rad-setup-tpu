# Date: Sept 2017

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
from telnetlib import Telnet

switch_serial=None
NUM_TRIES=4
SOCKET_TIMEOUT= 15
log_outf = None 

prev_DD_message=""
current_DD_message=""
sock=None
double_double_DD=0
power_switch=None

switch_port=0
# get_self_ip_address: gets the ip from the ethernet socket
def get_self_ip_address():
    global subnet

    ip_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        ip_socket.connect((subnet, 1027))
    except socket.error:
        return None
        
    return ip_socket.getsockname()[0] 

# start_app: starts the application via telnet. It sends the command line necesaary to run the benchmark withh all its arguments. it returns 0 if sucessfull, 
#returns 1 if there is connection refused and returns 2 if the board is unreachable
def start_app():
    global board_ip
    global exec_code
    global username
    global sock
    global PATH
    global arg_dic
    try:
       
        tn = telnetlib.Telnet(board_ip,timeout=30)
        tn.read_until(b'ogin: ',timeout=30)
        tn.write(username.encode('ascii') +b'\n')
        l=tn.read_very_eager()
        print(l)
        tn.read_until(b'assword: ',timeout=30)
        tn.write(user_password.encode('ascii') +b'\n')
        tn.read_until(b'$ ',timeout=30)       

        message='pkill '+exec_code+'\r\n'
        print(message)        
        tn.write(message.encode('ascii')) 
        l=tn.read_very_eager()
        print(l)
    
        message2='nohup '+PATH+exec_code+' '+get_self_ip_address()+' '+str(pc_port)+' '+ arg_dic[exec_code]+' &\r\n'
        print(message2)
        tn.write(message2.encode('ascii'))
        l=tn.read_very_eager()
        print(l)
        sleep(0.1)
        tn.close()
 
    except OSError as e:
        print(e)
        if(e.errno==errno.EHOSTUNREACH):
            return 2
        return 1
    except EOFError as e:
        print(e)        
        return 1
    return 0
# repeatedErrors: if two equal errors are received in sequence. it kills and restart the application and if there is two double errors in sequence, it restart the application 
def repeatedErrors():
    global prev_DD_message
    global current_DD_message
    global double_double_DD
    prev_DD_message=""
    current_DD_message=""
    write_logs(getTime() + " " +board_ip +" [INFO] Double DD, restarting application")
    if double_double_DD<4:
        write_logs(getTime() + " " +board_ip +" [INFO] Double DD, restarting application")
        double_double_DD+=1
        start_app()
    else:
        write_logs(getTime() + " " +board_ip +" [INFO] Double \"Double DD\", restarting the board")
        double_double_DD=0
        resetBoard()
    return
#resetBoard: restart the board by turn it off on the power switch
def resetBoard():
    global prev_DD_message
    global current_DD_message
    global pc_port
    global sock
    global power_switch
    prev_DD_message=""
    current_DD_message=""
    write_logs(getTime() + " " +board_ip +" [INFO] BOARD HARD RESET...")
    power_switch.reset_board()
    counter=0
    while(1):
        ret_value=start_app()
        if (ret_value!=0):
            if(counter==NUM_TRIES or ret_value==2):                
                power_switch.reset_board()
                counter=0
            else:
                sleep(1)
                counter+=1
            write_logs(getTime() + " " +board_ip +" [INFO] CONNECTION TO BOARD FAILED RETRYING")
        else:
            break

    write_logs(getTime() + " " +board_ip +" [INFO] EXPERIMENT RESUMED")
    return
#write_logs: just write a string on the log file
def write_logs(str):
    print(str, end = "\n")
    log_outf.write(str+"\n")
    log_outf.flush()
    return
#getTime: returns a string representing the current time
def getTime():
    return datetime.now().strftime("%d-%m-%Y-%H-%M-%S")
#openLog: creates and opens the log file
def openLog():
    global log_outf
    global exec_code
    date=getTime()
    filename_inj = "./logs/"+exec_code+"/log"+"_" + date +"_" +board_ip+".txt"
    filemode_inj = "a"
    log_outf = open(filename_inj, filemode_inj)
    write_logs(getTime() +" " +board_ip +" [INFO] starting radiation experiment...")
    return
# unexpectedOutputFunc: if the message received is not either one of the valid ones, the function justs log it.
def unexpectedOutputFunc():
    global isReconfigure
    global string


    write_logs(getTime() +" " +board_ip + " [INFO] unexpected output: " + string)
    return

#read_word: reads one byte and formats it in an hex string
def read_word(data,pos):
    string=""
    for i in range(4*pos,4*(pos+1)):
        string="0x{:02x}".format(data[i])[2:]+string
    return string

def main():
    global sock
    global string
    global current_DD_message
    global prev_DD_message
    global DATA_SIZE

    resetBoard()
    while True:                
        try:
            data, addr = sock.recvfrom(4*DATA_SIZE)
        except socket.timeout:
            start_app_ret=start_app()
            if (start_app_ret != 0):
                write_logs(getTime() + " " +board_ip +" [INFO] TIMEOUT... LINUX CRASHED")
                resetBoard()
            else:
                write_logs(getTime() +" " +board_ip+ " [INFO] TIMEOUT... APP CRASHED")
                write_logs(getTime() + " " +board_ip +" [INFO] EXPERIMENT RESUMED")               
        else:
            if(prev_DD_message==current_DD_message and prev_DD_message!=""):
                    
                    repeatedErrors()

            string=read_word(data,0)
            if(string[:2]=="aa"):
                write_logs(getTime() +" " +board_ip + " [PL] AA")
                prev_DD_message=""
                current_DD_message=""
            elif(string[:2]=="dd"):
                
                prev_DD_message=current_DD_message[:]

                current_DD_message=""
                for i in range(1,DATA_SIZE):
                    current_DD_message+=read_word(data,i)                   

                write_logs(getTime() + " " +board_ip +" [PL] DD "+current_DD_message)
                
            elif(string[:2]=="cc"):
                string=""
                for i in range(1,DATA_SIZE):
                    string+=read_word(data,i)
                write_logs(getTime() + " " +board_ip +" [PL] CC "+string)
                current_DD_message+=string
            else:
                unexpectedOutputFunc()
    return

#mess_size_dic: a dicionary with each benchamrks error message size
mess_size_dic={
        "lud":5,
        "lud_small":5,
        "lavamd":10,
        "hotspot_64":5,
        "l1_test":3,
        "fft":4,
        "fft_small":4,
        "qsort":2,
        "qsort_small":2,
        "matmul_400":4,
        "matmul_checksum":4,
        "matmul_600":4
        }

board_ip= sys.argv[1] # the DUT IP
pc_port = int(sys.argv[2]) #the host port where is will receive the DUT messages
exec_code= sys.argv[3]   # name of the benchamrk (should it be the same as the exec file on the DUT)
DATA_SIZE = mess_size_dic[exec_code]
switch_type= sys.argv[4] # power switch type
switch_ip=sys.argv[5] # power switch ip
switch_port= int(sys.argv[6]) # power switch port where the power supply of the DUT is connected
sleep_time= int(sys.argv[7]) # waiting time for the script. it should be larger enough for the DUT to boot
username=sys.argv[8] # DUT username
user_password=sys.argv[9]  # DUT username password
PATH="/home/" + username + "/benchmarks/" #path where the benchmarks are
# arg_dic: a dicionary with the arguments specific for each benchmark.
#this dictionary must stay here because PATH depends on the "username" argument
arg_dic={"lud":"1024 "+PATH+ "input_1024_th_1 "+PATH+"gold_1024_th_1",
        "lud_small":"512 "+PATH+ "input_512_th_1 "+PATH+"gold_512_th_1",
        "lavamd":"5 "+PATH+"input_distance_1_5 "+PATH+"input_charges_1_5 "+PATH+"output_gold_1_5",
        "hotspot_64":"256 256 100  "+PATH+"temp_256 "+PATH+"power_256 "+PATH+"gold_256",
        "l1_test":"",
        "fft":"21 "+PATH+"fft_input_21.bin "+PATH+"fft_gold_21.bin",
        "fft_small":"17 "+PATH+"fft_input_17.bin "+PATH+"fft_gold_17.bin",
        "qsort":"2000000 "+PATH+"qsort_input_2000000.bin "+PATH+"qsort_gold_2000000.bin",
        "qsort_small":"200000 "+PATH+"qsort_input_200000.bin "+PATH+"qsort_gold_200000.bin",
        "matmul_400": PATH+"matmul_input_400.bin"+" "+PATH+"matmul_gold_400.bin 400",
        "matmul_checksum": PATH+"matmul_input_400.bin"+" "+PATH+"matmul_gold_400.bin 400 matmul_crc_400.bin",
        "lavamd_checksum":"5 "+PATH+"input_distance_1_5 "+PATH+"input_charges_1_5 "+PATH+"output_gold_1_5",
        "matmul_600": PATH+"matmul_input_600.bin"+" "+PATH+"matmul_gold_600.bin 600"

        }


subnet = ".".join(board_ip.split(".")[:3]) + ".1"
power_switch = switch.Switch(switch_type,switch_port,switch_ip, sleep_time)   #creates a power switch object
a= get_self_ip_address()

sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM) # the UDP socket which receives the messages
sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
sock.bind((get_self_ip_address(), pc_port))
sock.settimeout(SOCKET_TIMEOUT) 
openLog()
try:
    main()
except KeyboardInterrupt as err:
    
    print(err)
