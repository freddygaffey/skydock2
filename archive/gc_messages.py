import hashlib
import threading
import time
from telemetry import telemetry_singlton, Passer
import json

class _GroundStaionMessages:
    """this class stores the floats that are deafauts in the FSM and also allow the FSM to ask questions to the ground station"""
    _instance = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self):
        if hasattr(self, '_initialized'):
            return
        self._initialized = True
        self.len_hash = 9
        self.messages = []
        self.ground_station_floats = {
            "takeoff_hight": 0,
            "scan_alt": 30,
            "scan_precision": 2
        }
        
        self.messages_lock = threading.Lock()
        self.floats_lock = threading.Lock()
        self.passer = Passer(self.passer_fun,{})

    def passer_fun(self,msg):
        if msg._type == "STATUSTEXT" and "gc: " in msg.text:
            print(f"passer_fun instance: {id(self)}")  # Add this
            message_text = msg.text
            print(message_text)
            print(f"BEFORE append: {self.messages}")  # Add this
            message_text = message_text[4:] # to remove the 
            message_text = message_text.replace("'",'"') 
            message_array = json.loads(message_text)
            print(message_array)
            # message_array[0] = message_array[0][1:]

            with self.messages_lock:
                self.messages.append(message_array)
                print(f"AFTER append: {self.messages}")  # Add this
                print(f"Lock acquired and appended: {message_array}")  # Add this
        
        # if msg._type == "NAMED_VALUE_FLOAT":
        #     print(msg)
        #     try:
        #         with cls.floats_lock:
        #             name = cls.find_key_in_float_keys(hash_str=msg.name,dict_of_keys=cls.ground_station_floats)
        #             cls.ground_station_floats[name] = msg.value
        #             print(cls.ground_station_floats)
        #             print(f"updated the floats array value {name} to {cls.ground_station_floats[name]}")
        #     except KeyError:
        #         print(f"Warning: Received NAMED_VALUE_FLOAT with unknown hash: {msg.name} (value: {msg.value})")


    def ask_question_bool(self,question:str) -> bool:
        print(f"ask_question_bool instance: {id(self)}")  # Add this
        telemetry_singlton.send_text_message(question)
        start_time = time.time()
        time_out = 15 # s
        while start_time + time_out > time.time():
            with self.messages_lock:
                for i in self.messages:
                    if question in i:
                        if i[1] == "accepted":
                            return True 
                        elif i[1] == "rejected": 
                            return False
                        else: raise ValueError(f"the ansewer to the questoin is not found it is {i}")
            time.sleep(0.25)
        with self.messages_lock:
            print(self.messages,"messages as seen by the ask wueston ")

        raise TimeoutError(f"user to too long to answer the queston {question = }")

gc_singlton = _GroundStaionMessages()

if __name__ == "__main__":
    # from telemetry import telemetry_singlton
    from passer import Passer, start_passers
    start_passers()
    while True:
        print(gc_singlton.ask_question_bool("what up"))









# import hashlib

# import threading
# import time
# from telemetry import telemetry_singlton, Passer

# # I found the videos from Intelligent Quads helpfull 
# # https://www.youtube.com/watch?v=kecnaxlUiTY
# # https://www.youtube.com/watch?v=6M7e7DDLTQc
# # https://www.youtube.com/watch?v=NTjEcHmqmu4

# # multi threading 
# # https://www.youtube.com/watch?v=STEOavXqXkQ

# class GroundStaionMessages:
#     len_hash = 9
#     messages = []
#     ground_station_floats = {
#         "takeoff_hight": 0,
#         "scan_alt": 30,
#         "scan_precision": 2
#     }
    
#     messages_lock = threading.Lock()
#     floats_lock = threading.Lock()

#     @classmethod
#     def get_floats(cls):
#         with cls.floats_lock:
#             return cls.ground_station_floats.copy()

#     @classmethod
#     def find_key_in_float_keys(cls,hash_str,dict_of_keys:dict=None):
#         keys = dict_of_keys
#         if keys == None:
#             keys = cls.get_floats()
#         for i in keys:
#             string = hashlib.sha1(i.encode()).hexdigest()[:cls.len_hash] 
#             if string == hash_str:
#                 return i
#         raise KeyError("the gc floats key can't be found")
            
#     @staticmethod
#     def encode_message(message):
#         # message = base64.b64encode(message.encode("utf-8")).decode("ascii")
#         return message  

#     @staticmethod
#     def decode_message(message):
        
#         # message = base64.b64decode(message.encode("ascii")).decode("utf-8")
#         return message

#     @classmethod
#     def get_latest_message(cls):
#         with cls.messages_lock:
#             try:
#                 return cls.messages[-1]
#             except IndexError:
#                 return cls.messages

#     @classmethod
#     def passer(cls, message):
#         if message._type == "STATUSTEXT" and "gc:" in message.text:
#             message_text = message.text
#             message_text = cls.decode_message(message_text)
#             message_text = message_text[3:]
#             message_array = eval(message_text)
#             message_array[0] = message_array[0][1:]

#             with cls.messages_lock:
#                 cls.messages.append(message_array)
        
#         if message._type == "NAMED_VALUE_FLOAT":
#             print(message)
#             try:
#                 with cls.floats_lock:
#                     name = cls.find_key_in_float_keys(hash_str=message.name,dict_of_keys=cls.ground_station_floats)
#                     cls.ground_station_floats[name] = message.value
#                     print(cls.ground_station_floats)
#                     print(f"updated the floats array value {name} to {cls.ground_station_floats[name]}")
#             except KeyError:
#                 print(f"Warning: Received NAMED_VALUE_FLOAT with unknown hash: {message.name} (value: {message.value})")

                
#     @classmethod
#     def ask_gc_question(cls,question):
#         question_to_send = f"drone: {question}"
#         if len(question) >= 43:
#             raise ValueError("question is to long") 

#         telemetry_singlton.send_text_message(cls.encode_message(question_to_send))

#         def check_for_message_retun_ans():
#             while True:
#                 time.sleep(0.5)
#                 message = cls.get_latest_message()
#                 if len(message) == 0: continue
#                 print(message[0],"message question")
#                 print(question,"function question")
#                 if question != message[0]: continue
#                 elif "accepted" == message[1]: return True
#                 elif "rejected" == message[1]: return False
#                 else: raise ValueError("idk what happed")
#         return check_for_message_retun_ans()


# gc_passser = Passer(GroundStaionMessages.passer,pram_and_time_dict={"STATUSTEXT":0.3})

# if __name__ == "__main__":
#     from passer import start_passers
#     from telemetry import telemetry_singlton 
#     start_passers(debug = True)
#     import time 
#     while 1:
#         print(type(GroundStaionMessages.find_key_in_float_keys("95c5b08e1")))
#         print(GroundStaionMessages.get_floats())
#         time.sleep(1)
        
        
#     #     print(GroundStaionMessages.get_floats())