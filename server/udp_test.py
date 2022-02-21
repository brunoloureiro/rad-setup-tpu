import socket
from multiprocessing import Process
import os
from multiprocessing import Lock
from time import sleep
s_print_lock = Lock()
udp=socket.SOCK_DGRAM

afm=socket.AF_INET
recv_ip="192.168.195.215"

def s_print(*a, **b):
    """Thread safe print function"""
    with s_print_lock:
        print(*a, **b)

def s_input(*a):

    with s_print_lock:
        msg=input(*a)
    return msg


def recv(recv_port):
    s2 = socket.socket(afm, udp)
    s2.bind((recv_ip, recv_port))
    while True:
        msg_recv=s2.recvfrom(1024)
        if msg_recv[0].decode()=="quit":
            s_print("user left\n")
            os._exit(0)
        s_print(str(recv_port)+" - "+msg_recv[1][0] + " : " + msg_recv[0].decode())


if __name__ == '__main__':
    recv_t= Process(target=recv,args=(10002,))
    recv_t2= Process(target=recv,args=(10003,))
    recv_t3= Process(target=recv,args=(10004,))

    recv_t2.start()
    recv_t.start()
    recv_t3.start()
    s = socket.socket(afm, udp)

    s.bind(("127.0.0.1", 10000))
    while True:
        sleep(1)
        recv_port = int(s_input("port: "))
        msg = s_input("Type your message: ")
        s.sendto(msg.encode(), (recv_ip, recv_port))
