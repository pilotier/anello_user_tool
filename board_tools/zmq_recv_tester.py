
import zmq

context = zmq.Context()
socket = context.socket(zmq.SUB)
socket.connect("tcp://10.0.0.25:9004")
socket.setsockopt_string(zmq.SUBSCRIBE, "")

while True:
    #print the raw data, not string 
    print(socket.recv()) 


    