from request_utils import send_request
from multiprocessing import Process
from foursquare import Foursquare
import os, sys, math, heapq, time, uuid

class ChatRoom:

    MIN_RADIUS = 0.15 #in kmeters, so 150 meters
    MAX_USERS_PER_ROOM = 7
    UNSTABLE_ROOM_THRESHOLD = 3
    INITIAL_MAX_RADIUS = 1.5 #1.5 kmeters
    chats = {}
    user2chat = {}
    chat2chat = {}

    def __init__(self, location, user_id):

        _4square = Foursquare(
            client_id=os.environ.get('FOURSQUARE_CLIENT_ID', None),
            client_secret=os.environ.get('FOURSQUARE_CLIENT_SECRET', None)
        )

        new_id = "chat-" + str(uuid.uuid4())
        while ( ChatRoom.get_chat(new_id) != None ):
            new_id = "chat-" + str(uuid.uuid4())
        
        self.ids = [ new_id ]
        self.members = {}
        self.center = location
        self.radius = ChatRoom.MIN_RADIUS
        self.messages = []
        self.tags = None

        old_messages = []
        to_clean = []

        for chat_id in ChatRoom.chats:
            chat_room = ChatRoom.get_chat(chat_id)
            if ( chat_room.was_skipped_by(user_id) ):
                continue
            if ( chat_room.is_stable() ):
                continue
            centers_distance = ChatRoom.distance(self.center, chat_room.center)
            if ( centers_distance <= self.radius + chat_room.radius or
                    ( centers_distance <= ChatRoom.INITIAL_MAX_RADIUS and
                        ChatRoom.tags_match(self, chat_room, _4square) ) ):
                for chat_id in chat_room.ids:
                    if ( chat_id not in ChatRoom.chat2chat ):
                        ChatRoom.chat2chat[chat_id] = self.ids[0]
                    if ( chat_id in ChatRoom.chats ):
                        to_clean.append(chat_id)
                self.ids.extend(chat_room.ids)
                self.tags = ChatRoom.common_tags(self, chat_room)
                self.members.update(chat_room.members)
                old_messages.append(chat_room.messages)

        for message in heapq.merge(*old_messages):
            self.messages.append(message)

        for chat_id in to_clean:
            del ChatRoom.chats[chat_id]
        ChatRoom.chats[self.ids[0]] = self
        self.add_user(user_id, location)

    def update_center_and_radius(self):

        n = len(self.members.keys())
        if ( n == 0 ):
            return
        R = 6371
        c_x = 0
        c_y = 0
        c_z = 0

        center = {}

        for user_id in self.members:
            location = self.members[user_id]["location"]
            latitude = math.radians(location["lat"])
            longitude = math.radians(location["long"])

            x = math.cos(latitude) * math.cos(longitude) * R
            y = math.cos(latitude) * math.sin(longitude) * R
            z = math.sin(latitude) * R

            c_x += x
            c_y += y
            c_z += z

        c_x /= n
        c_y /= n
        c_z /= n

        if ( ( math.fabs(c_x) < math.pow(10, -9) )
          and ( math.abs(c_y) < math.pow(10, -9) )
          and ( math.abs(c_z) < math.pow(10, -9) ) ):
            center["lat"] = 40.866667
            center["long"] = 34.566667
        else:
            hyp = math.sqrt(math.pow(c_x, 2) + math.pow(c_y, 2)) 
            center["lat"] = math.degrees(math.atan2(c_z, hyp))
            center["long"] = math.degrees(math.atan2(c_y, c_x))

        self.center = center

        radius = ChatRoom.MIN_RADIUS

        for user_id in self.members:
            location = self.members[user_id]["location"]
            distance = ChatRoom.distance(center, location)
            if ( distance > radius ):
                radius = distance + (ChatRoom.MIN_RADIUS / 3)

        self.radius = radius

        ChatRoom.assign_tags(self, None)

#TODO make this useful, currently not sending it because Android client
# makes no real use of this information
#        p = Process(target=do_update_center_and_radius,
#            args=(self.ids, center, radius))
#        p.daemon = True
#        p.start()

    def add_user(self, user_id, location):
        self.members[user_id] = {"location": location}
        ChatRoom.user2chat[user_id] = self.ids[0]
        self.update_center_and_radius()

    def remove_user(self, user_id):
        if ( user_id in self.members.keys() ):
            del self.members[user_id]
            del ChatRoom.user2chat[user_id]
#        if ( len(self.members.keys()) != 0 ):
#            self.update_center_and_radius()
#        else:
        if ( len(self.members.keys()) == 0 ):
            ChatRoom.remove_chat(self.ids[0])

    def update_user(self, user_id, user_data):
        if ( user_id in self.members.keys() ):
            if ( "location" in user_data ):
                self.members[user_id]["location"] = user_data["location"]
	    self.members[user_id]["nickname"] = user_data.get("nickname", None)
            self.members[user_id]["first_name"] = user_data.get("first_name", None)
            self.members[user_id]["full_name"] = user_data.get("full_name", None)
            self.members[user_id]["gender"] = user_data.get("gender", "unknown")
            self.members[user_id]["anonymous"] = user_data.get("anonymous", True)

    def is_full(self):
        return len(self.members.keys()) >= ChatRoom.MAX_USERS_PER_ROOM

    def is_stable(self):
        return len(self.members.keys()) > ChatRoom.UNSTABLE_ROOM_THRESHOLD

    def was_skipped_by(self, user_id):
        from users import User
        user = User.get(user_id)
        for chat_id in self.ids:
            if ( chat_id in user.skipped_chats ):
                return True
        return False

    def add_message(self, sender_id, message):
        timestamp = time.time() * 1000000
        heapq.heappush(self.messages, (timestamp, {
            "sender": sender_id,
            "message": message
        }))
        return timestamp

    @staticmethod
    def get_chat(chat_id):
        if ( chat_id == None ):
            return None
        chat_room = ChatRoom.chats.get(chat_id,
            ChatRoom.get_chat(ChatRoom.chat2chat.get(chat_id, None)))
        return chat_room

    @staticmethod
    def remove_chat(chat_id):
        if ( chat_id == None ):
            return
        chat_room = ChatRoom.chats.get(chat_id, None)
        if ( not chat_room ):
            return
        for chat_id in chat_room.ids:
            if ( chat_id in ChatRoom.chats.keys() ):
                del ChatRoom.chats[chat_id]
            if ( chat_id in ChatRoom.chat2chat.keys() ):
                del ChatRoom.chat2chat[chat_id]

    @staticmethod
    def distance(location1, location2):
        R = 6371
        lat1 = math.radians(location1["lat"])
        lat2 = math.radians(location2["lat"])
        d_lat = math.radians(location2["lat"] - location1["lat"])
        d_long = math.radians(location2["long"] - location1["long"])

        a = math.pow(math.sin(d_lat/2), 2) + math.cos(lat1) * math.cos(lat2) * math.pow(math.sin(d_long/2), 2)
        c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
        return R * c

    @staticmethod
    def closest(user_id, location):
        closest = None
        min_distance = sys.maxint
        for chat_id in ChatRoom.chats:
            chat_room = ChatRoom.get_chat(chat_id)
            if ( chat_room.is_full() ):
                continue
            if ( chat_room.was_skipped_by(user_id) ):
                continue
            distance = ChatRoom.distance(location, chat_room.center) 
            if ( distance < chat_room.radius ):
                if ( not closest ):
                    closest = chat_room
                    min_distance = distance
                elif distance < min_distance:
                    closest = chat_room
                    min_distance = distance
        return closest

    @staticmethod
    def assign_tags(chat_room, _4square):
        if ( _4square == None ):
            _4square = Foursquare(
                client_id=os.environ.get('FOURSQUARE_CLIENT_ID', None),
                client_secret=os.environ.get('FOURSQUARE_CLIENT_SECRET', None)
            )
        if ( chat_room.tags != None and chat_room.tags != 'unknown' ):
            return
        center = chat_room.center
        ll = "{}, {}".format(center["lat"], center["long"])
        chat_room.tags = 'unknown'
        try:
            result = _4square.venues.search(params={
              'll': ll,
              'radius': '15', 'limit': 3
            })
            if ( len(result['venues']) > 0 ):
                tags = [ x['name'] for x in result['venues'] ]
                chat_room.tags = tags
        except:
            pass

    @staticmethod
    def tags_match(chat_room1, chat_room2, _4square):
        targets = []
        if ( chat_room1.tags == None ):
            targets.append(chat_room1)
        if ( chat_room2.tags == None ):
            targets.append(chat_room2)
        for chat_room in targets:
            ChatRoom.assign_tags(chat_room, _4square)
        if ( chat_room1.tags == 'unknown'
                or chat_room2.tags == 'unknown' ):
            return False
        veredict = False
        for tag1 in chat_room1.tags:
            tag1 = tag1.replace(' ','').lower()
            for tag2 in chat_room2.tags:
                tag2 = tag2.replace(' ','').lower()
                veredict = veredict or ( (tag1 == tag2)
                    or (tag1 in tag2) or (tag2 in tag1) )
        return veredict

    @staticmethod
    def common_tags(chat_room1, chat_room2):
        if ( chat_room1.tags == None or chat_room1.tags == 'unknown' ):
            return None
        if ( chat_room2.tags == None or chat_room2.tags == 'unknown' ):
            return None
        tags = []
        for tag1 in chat_room1.tags:
            _tag1 = tag1.replace(' ','').lower()
            for tag2 in chat_room2.tags:
                _tag2 = tag2.replace(' ','').lower()
                if ( (tag1 == tag2) or (tag1 in tag2) ):
                    tags.append(tag1)
                elif ( tag2 in tag1 ):
                    tags.append(tag2)
        return tags

    @staticmethod
    def at_chat(user_id):
        return ChatRoom.user2chat.get(user_id, None)

    @staticmethod
    def assign_chat(user_id, location):
        from users import User
        u = User.get(user_id)
        if ( location == "unknown" ):
            u.liked_users = []
            return None, []
        chat_id = ChatRoom.at_chat(user_id)
        if ( chat_id ):
            chat_room = ChatRoom.get_chat(chat_id)
            if ( ChatRoom.distance(chat_room.center, location) > chat_room.radius ):
                chat_room.remove_user(user_id)
                return ChatRoom.assign_chat(user_id, location)
            return chat_id, chat_room.ids
        else:
            u.liked_users = []
            closest = ChatRoom.closest(user_id, location)
            if ( closest ):
                closest.add_user(user_id, location)
                return closest.ids[0], closest.ids
            else:
                chat_room = ChatRoom(location, user_id)
                u.skipped_chats = []
                return chat_room.ids[0], chat_room.ids

def do_update_center_and_radius(chat_ids, center, radius):

    headers = {
        "X-Parse-Application-Id": os.environ.get("PARSE_APPLICATION_ID", None),
        "X-Parse-REST-API-Key": os.environ.get("PARSE_REST_API_KEY", None),
        "Content-Type":"application/json"
    }

    data = {
        "action": "com.lespi.aki.receivers.INCOMING_GEOFENCE_UPDATE",
        "center": center,
        "radius": radius
    }

    payload = {
        "channels": chat_ids, 
        "data" : data
    }

    response = send_request('POST', "https://api.parse.com/1/push",
        payload=payload, headers=headers) 
