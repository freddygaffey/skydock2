
import hashlib

import threading
import time
from telemetry import telm_singleton 

# I found the videos from Intelligent Quads helpfull 
# https://www.youtube.com/watch?v=kecnaxlUiTY
# https://www.youtube.com/watch?v=6M7e7DDLTQc
# https://www.youtube.com/watch?v=NTjEcHmqmu4

# multi threading 
# https://www.youtube.com/watch?v=STEOavXqXkQ

class GroundStaionMessages:
    messages = []
    ground_station_floats = {
        "takeoff_hight": 0,
        "scan_alt": 30,
        "scan_precision": 2
    }
    
    messages_lock = threading.Lock()
    floats_lock = threading.Lock()

    @classmethod 
    def get_floats(cls):
        with cls.floats_lock:
            return cls.ground_station_floats

    @classmethod
    def find_key_from_hash(cls,hash_str=None,float_key=None,float_keys_dict = None):
        if float_keys_dict == None:
            float_keys_dict = cls.get_floats()

        len_hash = 10
        if hash_str == None:
            string = hashlib.sha1(float_key.encode()).hexdigest()[:len_hash] 
            return string

        if float_key == None:
            float_key_hash = hashlib.sha1(float_key.encode()).hexdigest()[:len_hash]

            for i in float_keys_dict:
                string = hashlib.sha1(i.encode()).hexdigest()[:len_hash] 
                if string == float_key_hash:
                    return i
            
    @staticmethod
    def encode_message(message):
        # message = base64.b64encode(message.encode("utf-8")).decode("ascii")
        return message  

    @staticmethod
    def decode_message(message):
        
        # message = base64.b64decode(message.encode("ascii")).decode("utf-8")
        return message

    @classmethod
    def get_latest_message(cls):
        with cls.messages_lock:
            try:
                return cls.messages[-1]
            except IndexError:
                return cls.messages

    @classmethod
    def passer(cls, message):
        if message._type == "STATUSTEXT" and "gc:" in message.text:
            message_text = message.text
            message_text = cls.decode_message(message_text)
            message_text = message_text[3:]
            message_array = eval(message_text)
            message_array[0] = message_array[0][1:]

            with cls.messages_lock:
                cls.messages.append(message_array)

        if message._type == "NAMED_VALUE_FLOAT":
            name = cls.find_key_from_hash(hash_str=message.name)
            cls.get_floats()[name] = message.value
            print(f"updated the floats array value {name} to {message.value}")


                
    @classmethod
    def ask_gc_question(cls,question):
        question_to_send = f"drone: {question}"
        if len(question) >= 43:
            raise ValueError("question is to long") 
        
        telm_singleton.send_text_message(cls.encode_message(question_to_send))

        def check_for_message_retun_ans():
            while True:
                time.sleep(0.5)
                message = cls.get_latest_message()

                if len(message) == 0: continue
                print(message[0],"message question")
                print(question,"function question")
                if question != message[0]: continue
                elif "accepted" == message[1]: return True
                elif "rejected" == message[1]: return False
                else: raise ValueError("idk what happed")

        return check_for_message_retun_ans()