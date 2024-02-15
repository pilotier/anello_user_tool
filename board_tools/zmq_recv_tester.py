
import zmq

context = zmq.Context()
socket = context.socket(zmq.SUB)
socket.connect("tcp://127.0.0.1:9004")
socket.setsockopt_string(zmq.SUBSCRIBE, "anello")

while True:
    #print the raw data, not string 
    print(socket.recv()) 


    