from flask import Flask, make_response, request
from flask.ext.login import LoginManager, login_user, logout_user,\
login_required, current_user, UserMixin
from flask.ext.sqlalchemy import SQLAlchemy, Session
from sqlalchemy.orm.exc import NoResultFound, MultipleResultsFound

from request_utils import send_request

from multiprocessing import Process, Pool
from threading import Timer, Lock
import os, json, logging, math, sys, uuid, heapq, time, copy

logging.basicConfig(level=logging.DEBUG)

server = Flask(__name__)
server.secret_key = os.environ.get("SECRET_KEY", os.urandom(24))
server.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get(
    'DATABASE_URL', 'postgresql:///local_database')

login_manager = LoginManager(server)
database = SQLAlchemy(server)

class MutualInterest(database.Model):

    __tablename__ = 'mutual'
    id = database.Column(database.Integer, primary_key=True)
    uid1 = database.Column(database.String(20))
    uid2 = database.Column(database.String(20))

    def __init__(self, uid1, uid2):
        self.uid1 = uid1
        self.uid2 = uid2

    def __repr__(self):
        return "<Mutual {} & {}>".format(self.uid1, self.uid2)

class StoredUser(database.Model):

    __tablename__ = 'person'
    id = database.Column(database.Integer, primary_key=True)
    uid = database.Column(database.String(20), unique=True)
    active = database.Column(database.Boolean)

    def __init__(self, user_id, active=False):
        self.uid = user_id
        self.active = active

    def __repr__(self):
        return "<Username {}>".format(self.uid)

class User(UserMixin):

    MAX_INACTIVE_TIME = 10 * 60 #10 minutes
    users = {}

    def __init__(self, user_id, active=True):

        self.uid = user_id
        self.active = active
        self.skipped_chats = []
        self.terminate_timer = None
        self.liked_users = []
        self.lock = Lock()
        self.flag_mutual_interest = False

        try:
            StoredUser.query.filter(StoredUser.uid == user_id).one()
        except NoResultFound:
            database.session.add(StoredUser(user_id))
            database.session.commit()
        except MultipleResultsFound:
            for user in StoredUser.query.all():
                database.session.remove(user)
            database.session.add(StoredUser(user_id))
            database.session.commit()

        if ( not user_id in User.users ):
            User.users[user_id] = self

    def is_authenticated(self):
        return True

    def is_active(self):
        return True

    def is_anonymous(self):
        return False

    def get_id(self):
        return unicode(self.uid)

    def terminate(self):

        chat_id = ChatRoom.at_chat(self.uid)
        if ( chat_id ):
            ChatRoom.get_chat(chat_id).remove_user(self.uid)

    def set_terminate_timer(self):

        if ( self.terminate_timer ):
            self.terminate_timer.cancel()

        self.terminate_timer = Timer(User.MAX_INACTIVE_TIME, self.terminate)
        self.terminate_timer.start()

    def cancel_terminate_timer(self):

        if ( self.terminate_timer ):
            self.terminate_timer.cancel()

        self.terminate_timer = None

    def like(self, user):

        user.lock.acquire()
        self.lock.acquire()

        try:

            uid1 = self.get_id()
            uid2 = user.get_id()

            if ( not uid2 in self.liked_users ):
                self.liked_users.append(uid2)

                if ( uid1 in user.liked_users ):

                    repeats = len(MutualInterest.query.filter(
                        MutualInterest.uid1 == uid1,
                        MutualInterest.uid2 == uid2
                    ).all())
                    repeats += len(MutualInterest.query.filter(
                        MutualInterest.uid1 == uid2,
                        MutualInterest.uid2 == uid1
                    ).all())
                    if ( repeats > 0 ):
                        return

                    database.session.add(MutualInterest(uid1, uid2))
                    database.session.commit()

                    self.flag_mutual_interest = True
                    user.flag_mutual_interest = True
                    p = Process(target=do_notify_mutual_interest,
                        args=(uid1, uid2))
                    p.daemon = True
                    p.start()

        finally:
            self.lock.release()
            user.lock.release()

    def dislike(self, user):

        user.lock.acquire()
        self.lock.acquire()

        try:

            uid1 = self.get_id()
            uid2 = user.get_id()

            if ( uid2 in self.liked_users ):
                self.liked_users.remove(uid2)

        finally:
            self.lock.release()
            user.lock.release()

    def do_get_stored(self):
        return StoredUser.query.filter(StoredUser.uid == self.uid).first()

    @staticmethod
    def get(uid):
        return User.users.get(uid, None)

    @staticmethod
    def get_stored(uid):
        u = User.users.get(uid, None)
        if ( u != None ):
            return u.do_get_stored()
        return None

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

    if ( response["success"] ):
        logging.info("Message sent to Parse push notifications system")
    else:
        logging.info("Cannot send message to Parse push notifications system")

class ChatRoom:

    MIN_RADIUS = 0.1 #in kmeters
    MAX_USERS_PER_ROOM = 7
    UNSTABLE_ROOM_THRESHOLD = 3
    chats = {}
    user2chat = {}
    chat2chat = {}

    def __init__(self, location, user_id):

        new_id = "chat-" + str(uuid.uuid4())
        while ( ChatRoom.get_chat(new_id) != None ):
            new_id = "chat-" + str(uuid.uuid4())
        
        self.ids = [ new_id ]
        self.members = {}
        self.center = location
        self.radius = ChatRoom.MIN_RADIUS
        self.messages = []

        old_messages = []
        to_clean = []

        for chat_id in ChatRoom.chats:
            chat_room = ChatRoom.get_chat(chat_id)
            if ( chat_room.was_skipped_by(user_id) ):
                continue
            if ( chat_room.is_stable() ):
                continue
            if ( ChatRoom.distance(self.center, chat_room.center) <= self.radius + chat_room.radius ):
                for chat_id in chat_room.ids:
                    if ( chat_id not in ChatRoom.chat2chat ):
                        ChatRoom.chat2chat[chat_id] = self.ids[0]
                    if ( chat_id in ChatRoom.chats ):
                        to_clean.append(chat_id)
                self.ids.extend(chat_room.ids)
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
                radius = distance

        self.radius = radius

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
        if ( len(self.members.keys()) != 0 ):
            self.update_center_and_radius()
        else:
            ChatRoom.remove_chat(self.ids[0])

    def is_full(self):
        return len(self.members.keys()) >= ChatRoom.MAX_USERS_PER_ROOM

    def is_stable(self):
        return len(self.members.keys()) > ChatRoom.UNSTABLE_ROOM_THRESHOLD

    def was_skipped_by(self, user_id):
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
    def at_chat(user_id):
        return ChatRoom.user2chat.get(user_id, None)

    @staticmethod
    def assign_chat(user_id, location):
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


@login_manager.user_loader
def load_user(user_id):
    return User.get(user_id)

@login_manager.unauthorized_handler
def unauthorized():
    response = make_response(json.dumps({
        'server':'you are unauthorized',
        'code':'error'
    }), 200)
    response.headers["WWW-Authenticate"] = "Basic realm=\"you must authenticate with Basic method\""
    response.headers["Content-Type"] = "application/json"
    return response

@server.route('/', methods=['GET', 'POST'])
def index():

    users = []
    for user in User.users:
        u = User.get_stored(user)
        u_ = User.get(user)
        users.append({
            'user_id' : u.uid,
            'status' : 'active' if u.active else 'inactive',
            'liked': u_.liked_users
        })

    chats = []
    for chat_id in ChatRoom.chats:
        chat_room = ChatRoom.get_chat(chat_id)
        chats.append({
            "ids": chat_room.ids,
            "center": chat_room.center,
            "radius": chat_room.radius,
            "members": chat_room.members,
            "messages": [ x[1] for x in chat_room.messages ]
        })

    response = make_response(json.dumps({
        'server':'alive',
        'users': users,
        'chats': chats,
        'code': "ok"
    }), 200)
    response.headers["Content-Type"] = "application/json"
    return response

@server.route('/presence', methods=['GET'])
def get_presence():

    status = {
        'server' : 'you must send presence',
        'code' : 'ok',
        'user_id' : None
    }

    if ( current_user.is_authenticated() ):
        status['server'] = 'you are {}'.format(current_user.get_id())
        status['code'] = 'ok'
        status['user_id'] = current_user.get_id()

    response = make_response(json.dumps(status), 200)
    response.headers["Content-Type"] = "application/json"
    return response

def do_send_presence(chat_ids, user_data):

    if ( len(chat_ids) == 0 ):
        return

    headers = {
        "X-Parse-Application-Id": os.environ.get("PARSE_APPLICATION_ID", None),
        "X-Parse-REST-API-Key": os.environ.get("PARSE_REST_API_KEY", None),
        "Content-Type":"application/json"
    }

    user_data["action"] = "com.lespi.aki.receivers.INCOMING_USER_INFO_UPDATE"

    payload = {
        "channels": chat_ids, 
        "data" : user_data
    }

    response = send_request('POST', "https://api.parse.com/1/push",
         payload=payload, headers=headers) 

    if ( response["success"] ):
        logging.info("Message sent to Parse push notifications system")
    else:
        logging.info("Cannot send message to Parse push notifications system")


@server.route('/presence/<user_id>', methods=['POST'])
def send_presence(user_id):

    try:
        data = request.json
        if ( data == None ):
            response = make_response(json.dumps({'server':'payload must be valid json', 'code':'error'}), 200)
            response.headers["Content-Type"] = "application/json"
            return response
        data = dict(data)
        if ( data == None ):
            response = make_response(json.dumps({'server':'payload must be valid json', 'code':'error'}), 200)
            response.headers["Content-Type"] = "application/json"
            return response
    except:
        response = make_response(json.dumps({'server':'payload must be valid json', 'code':'error'}), 200)
        response.headers["Content-Type"] = "application/json"
        return response

    user_data = {}

    first_name = data.get('first_name', None)
    if ( first_name != None ):
        user_data["first_name"] = first_name

    full_name = data.get('full_name', None)
    if ( full_name != None ):
        user_data["full_name"] = full_name

    gender = data.get('gender', None)
    if ( gender != None ):
        user_data["gender"] = gender

    nickname = data.get('nickname', None)
    if ( nickname != None ):
        user_data["nickname"] = nickname

    anonymous = data.get('anonymous', None)
    if ( anonymous == None ):
        response = make_response(json.dumps({'server':'anonymous field cannot be ommitted!', 'code':'error'}), 200)
        response.headers["Content-Type"] = "application/json"
        return response

    location = data.get('location', None)
    if ( location == None ):
        response = make_response(json.dumps({'server':'location field cannot be ommitted!', 'code':'error'}), 200)
        response.headers["Content-Type"] = "application/json"
        return response

    user_data["from"] = user_id
    user_data["anonymous"] = anonymous
    user_data["location"] = location

    if ( location != "unknown" ):
        location["lat"] = float(location["lat"])
        location["long"] = float(location["long"])

    if ( current_user.is_authenticated() ):
        logging.info("You are already authenticated")
        if ( current_user.get_id() != user_id ):
            logging.info("But you are "+current_user.get_id()+", not "+user_id)
            response = make_response(json.dumps({'server':'presence fail (you are someone else)', 'code':'error'}), 200)
        else:
            u = User.get_stored(user_id)
            u.active = True
            database.session.add(u)
            database.session.commit()
            u_ = User.get(user_id)
            u_.cancel_terminate_timer()
            logging.info("Presence sent ok")
            chat_room, chat_ids = ChatRoom.assign_chat(user_id, location)

            p = Process(target=do_send_presence,
                args=(chat_ids, user_data))
            p.daemon = True
            p.start()

            response = {
                'server':'presence sent (already authenticated)',
                'chat_room': chat_room,
                'code':'ok'
            }
            if ( u_.flag_mutual_interest ):
                response["update_mutual_interests"] = True
            response = make_response(json.dumps(response), 200)
    else:

        User(user_id)
        u = User.get_stored(user_id)
        if ( login_user(User.get(user_id), remember=True) ):
            u.active = True
            database.session.add(u)
            database.session.commit()
            u_ = User.get(user_id)
            u_.cancel_terminate_timer()
            logging.info("Presence sent ok (by logging)")
            chat_room, chat_ids = ChatRoom.assign_chat(user_id, location)

            p = Process(target=do_send_presence,
                args=(chat_ids, user_data))
            p.daemon = True
            p.start()

            response = {
                'server':'presence sent (just authenticated)',
                'chat_room': chat_room,
                'code':'ok',
                'timestamp':str(int(time.time() * 1000000)).replace("L", "")
            }
            if ( u_.flag_mutual_interest ):
                response["update_mutual_interests"] = True
            response = make_response(json.dumps(response), 200)
        else:
            logging.info("Presence sent not ok (login failed)")
            response = make_response(json.dumps({'server':'presence fail (login fail)', 'code':'error'}), 200)

    response.headers["content-type"] = "application/json"
    return response

@server.route('/inactive', methods=['POST'])
@login_required
def send_inactive():

    user_id = current_user.get_id()

    u = User.get_stored(user_id)
    u.active = False
    database.session.add(u)
    database.session.commit()

    User.get(user_id).set_terminate_timer()

    response = make_response(json.dumps({'server':'{} just became inactive'.format(user_id), 'code':'ok'}), 200)
    response.headers["Content-Type"] = "application/json"
    return response

@server.route('/skip', methods=['POST'])
@login_required
def send_skip():

    user_id = current_user.get_id()

    u = User.get_stored(user_id)
    u.active = False
    database.session.add(u)
    database.session.commit()

    u_ = User.get(user_id)
    u_.liked_users = []

    chat_id = ChatRoom.at_chat(user_id)
    if ( chat_id ):
        chat_room = ChatRoom.get_chat(chat_id)
        User.get(user_id).skipped_chats.extend(chat_room.ids)
        chat_room.remove_user(user_id)
    else:
        response = make_response(json.dumps({'server':'{} is not in a chat room'.format(user_id), 'code':'error'}), 200)
    logout_user()

    response = make_response(json.dumps({'server':'{} just left'.format(user_id), 'code':'ok'}), 200)
    response.headers["Content-Type"] = "application/json"
    return response

@server.route('/exit', methods=['POST'])
@login_required
def send_exit():

    user_id = current_user.get_id()

    u = User.get_stored(user_id)
    u.active = False
    database.session.add(u)
    database.session.commit()

    u_ = User.get(user_id)
    u_.liked_users = []

    chat_id = ChatRoom.at_chat(user_id)
    if ( chat_id ):
        ChatRoom.get_chat(chat_id).remove_user(user_id)
    else:
        response = make_response(json.dumps({'server':'{} is not in a chat room'.format(user_id), 'code':'error'}), 200)
    logout_user()

    response = make_response(json.dumps({'server':'{} just left'.format(user_id), 'code':'ok'}), 200)
    response.headers["Content-Type"] = "application/json"
    return response

@server.route('/members', methods=['GET'])
@login_required
def get_members():

    user_id = current_user.get_id()
    chat_id = ChatRoom.at_chat(user_id)
    if ( chat_id ):
        members = ChatRoom.get_chat(chat_id).members
        response = make_response(json.dumps({'server':'{} retrieved chat {} members list'.format(user_id, chat_id), 'code':'ok', 'members':members}), 200)
    else:
        response = make_response(json.dumps({'server':'{} is not in a chat room'.format(user_id), 'code':'error'}), 200)

    response.headers["Content-Type"] = "application/json"
    return response

def get_msgs_after_tstamp(amount, source, after):

    messages = []

    all_m = copy.deepcopy(source)
    while ( len(all_m) > 0 and amount > 0 ):
        message = heapq.heappop(all_m)
        if ( message[0] <= after ):
            continue
        messages.append(message)
        amount = amount - 1

    return messages

@server.route('/message/<int:amount>', methods=['GET'])
@server.route('/message', methods=['GET'])
@login_required
def get_messages(amount=10):

    user_id = current_user.get_id()
    chat_id = ChatRoom.at_chat(user_id)
    if ( chat_id ):

        source = ChatRoom.get_chat(chat_id).messages

        after = request.args.get("next", None)
        if ( after ):
            try:
                after = int(after)
            except ValueError:
                response = make_response(json.dumps({'server':"\'next\' argument requires a number, cannot be {}".format(after), 'code':'error'}), 200)
                response.headers["Content-Type"] = "application/json"
                return response

            messages = get_msgs_after_tstamp(amount, source, after)
        else:
            messages = heapq.nsmallest(amount, source)

        next = None if ( len(messages) == 0 ) else messages[-1][0]
        remaining = len(get_msgs_after_tstamp(1, source, next)) if next else 0
        finished = remaining == 0

        messages = [ {
            "sender": x[1]["sender"],
            "message": x[1]["message"],
            "timestamp": str(int(x[0])).replace("L", "")
        } for x in messages ]

        response = {
            'server': '{} retrieved {} messages from chat {}'.format(user_id,
                len(messages), chat_id),
            'code': 'ok',
            'messages': messages,
            'next': str(int(next)).replace("L", "") if next else None,
            'finished': finished
        }

        u = User.get(user_id)
        if ( u.flag_mutual_interest ):
            response["update_mutual_interests"] = True
        response = make_response(json.dumps(response), 200)

    else:
        response = make_response(json.dumps({'server':'{} is not in a chat room'.format(user_id), 'code':'error'}), 200)

    response.headers["Content-Type"] = "application/json"
    return response

def do_send_message(sender, chat_ids, message):

    if len(chat_ids) == 0:
        return

    headers = {
        "X-Parse-Application-Id": os.environ.get("PARSE_APPLICATION_ID", None),
        "X-Parse-REST-API-Key": os.environ.get("PARSE_REST_API_KEY", None),
        "Content-Type":"application/json"
    }

    data = {
        "from": sender,
        "message": message["message"],
        "timestamp": str(int(message["timestamp"])).replace("L", ""),
        "action": "com.lespi.aki.receivers.INCOMING_MESSAGE",
    }

    payload = {
        "where": {
            "inactive": True,
            "channels": {
                "$in": chat_ids
            }
        },
        "data" : data
    }

    response = send_request('POST', "https://api.parse.com/1/push",
         payload=payload, headers=headers) 

    if ( response["success"] ):
        logging.info("Message sent to Parse push notifications system")
    else:
        logging.info("Cannot send message to Parse push notifications system")

@server.route('/message', methods=['POST'])
@login_required
def send_message():

    try:
        data = request.json
        if ( data == None ):
            response = make_response(json.dumps({'server':'payload must be valid json', 'code':'error'}), 200)
            response.headers["Content-Type"] = "application/json"
            return response
        data = dict(data)
        if ( data == None ):
            response = make_response(json.dumps({'server':'payload must be valid json', 'code':'error'}), 200)
            response.headers["Content-Type"] = "application/json"
            return response
    except:
        response = make_response(json.dumps({'server':'payload must be valid json', 'code':'error'}), 200)
        response.headers["Content-Type"] = "application/json"
        return response

    message = data.get('message', None)

    if ( message == None ):
        response = make_response(json.dumps({'server':'message field cannot be ommitted!', 'code':'error'}), 200)
        response.headers["Content-Type"] = "application/json"
        return response

    current_chat_id = ChatRoom.at_chat(current_user.get_id())
    if ( current_chat_id ):
        chat_room = ChatRoom.get_chat(current_chat_id)
        if ( chat_room == None ):
            response = make_response(json.dumps({'server':'user ' + current_user.get_id() + '\'s current chat_room is gone!', 'code':'error'}), 200)
            response.headers["Content-Type"] = "application/json"
            return response
        else:
            timestamp = chat_room.add_message(current_user.get_id(), message)

            should_push = False
            for member_id in chat_room.members:
                member = User.get_stored(member_id)
                if ( not member.active ):
                    should_push = True
                    break

            if ( should_push ):

                chat_ids = copy.deepcopy(chat_room.ids)
                p = Process(target=do_send_message,
                    args=(current_user.get_id(), chat_ids, {
                      "message": message,
                      "timestamp": timestamp
                    })
                )
                p.daemon = True
                p.start()

            logging.info("just started ~send_message~ process")
            response = make_response(json.dumps({'server':'message sent', 'code':'ok'}), 200)
            response.headers["content-type"] = "application/json"
            return response
    else:
        response = make_response(json.dumps({'server':current_user.get_id() + ' is not in a chat_room!', 'code':'error'}), 200)
        response.headers["Content-Type"] = "application/json"
        return response

def do_notify_mutual_interest(uid1, uid2):

    chat_ids = []

    chat_id1 = ChatRoom.at_chat(uid1)
    if ( chat_id1 ):
        chat_room = ChatRoom.get_chat(chat_id1)
        chat_ids.extend(chat_room.ids)

    chat_id2 = ChatRoom.at_chat(uid2)
    if ( chat_id2 ):
        chat_room = ChatRoom.get_chat(chat_id2)
        chat_ids.extend(chat_room.ids)

    if ( len(chat_ids) == 0 ):
        return

    headers = {
        "X-Parse-Application-Id": os.environ.get("PARSE_APPLICATION_ID", None),
        "X-Parse-REST-API-Key": os.environ.get("PARSE_REST_API_KEY", None),
        "Content-Type":"application/json"
    }

    user_data = {
        "action" : "com.lespi.aki.receivers.INCOMING_MUTUAL_INTEREST_UPDATE",
        "uid1": uid1,
        "uid2": uid2
    }

    payload = {
        "where": {
            "channels": {
                "$in": chat_ids
            },
            "uid": {
                "$in": [ uid1, uid2 ]
            }
        },
        "channels": chat_ids,
        "data" : user_data
    }

    response = send_request('POST', "https://api.parse.com/1/push",
         payload=payload, headers=headers) 

    if ( response["success"] ):
        logging.info("Message sent to Parse push notifications system")
    else:
        logging.info("Cannot send message to Parse push notifications system")


@server.route('/like/<user_id>', methods=['POST'])
@login_required
def send_like(user_id):

    current_id = current_user.get_id()
    current_u = User.get(current_id)

    liked_u = User.get(user_id)
    if ( liked_u == None ):
        response = make_response(json.dumps({'server':'{} does not exist'.format(user_id), 'code':'error'}), 200)
        response.headers["Content-Type"] = "application/json"
        return response
    if ( current_id == user_id ):
        response = make_response(json.dumps({'server':'{} cannot like oneself'.format(user_id), 'code':'error'}), 200)
        response.headers["Content-Type"] = "application/json"
        return response

    chat_id = ChatRoom.at_chat(current_id)
    if ( chat_id ):
        chat_room = ChatRoom.get_chat(chat_id)
        if ( user_id in chat_room.members ):
            current_u.like(liked_u)
            response = make_response(json.dumps({'server':'{} is interested in {}'.format(current_id, user_id), 'code':'ok'}), 200)
            response.headers["Content-Type"] = "application/json"
            return response

    response = make_response(json.dumps({'server':'{} is not in the same chat_room as you'.format(user_id), 'code':'error'}), 200)
    response.headers["Content-Type"] = "application/json"
    return response

@server.route('/dislike/<user_id>', methods=['POST'])
@login_required
def send_dislike(user_id):

    current_id = current_user.get_id()
    current_u = User.get(current_id)

    disliked_u = User.get(user_id)
    if ( disliked_u == None ):
        response = make_response(json.dumps({'server':'{} does not exist'.format(user_id), 'code':'error'}), 200)
        response.headers["Content-Type"] = "application/json"
        return response
    if ( current_id == user_id ):
        response = make_response(json.dumps({'server':'{} cannot like oneself'.format(user_id), 'code':'error'}), 200)
        response.headers["Content-Type"] = "application/json"
        return response

    current_u.dislike(disliked_u)
    response = make_response(json.dumps({'server':'{} lost interest in {}'.format(current_id, user_id), 'code':'ok'}), 200)
    response.headers["Content-Type"] = "application/json"
    return response

@server.route('/mutual', methods=['GET'])
@login_required
def get_mutual():

    current_id = current_user.get_id()
    u = User.get(current_id)
    u.flag_mutual_interest = False

    results = []

    mutuals = MutualInterest.query.filter(
        MutualInterest.uid1 == current_id
    )
    for mutual in mutuals:
        results.append({
            'uid': mutual.uid2
        })
    mutuals = MutualInterest.query.filter(
        MutualInterest.uid2 == current_id
    )
    for mutual in mutuals:
        results.append({
            'uid': mutual.uid1
        })

    response = make_response(json.dumps({
        'server':'retrieved {}\'s mutual interests'.format(current_id),
        'mutuals': results,
        'code':'ok'
    }), 200)
    response.headers["Content-Type"] = "application/json"
    return response

@server.route('/shutdown', methods=['POST'])
def shutdown():

    auth = os.environ.get("SHUTDOWN_AUTHORIZATION", None)
    if ( auth == None ):
        response = make_response(json.dumps({'server':'shutdown not allowed', 'code':'error'}), 200)
        response.headers["Content-Type"] = "application/json"
        return response

    try:
        data = request.json
        if ( data == None ):
            response = make_response(json.dumps({'server':'payload must be valid json', 'code':'error'}), 200)
            response.headers["Content-Type"] = "application/json"
            return response
        data = dict(data)
        if ( data == None ):
            response = make_response(json.dumps({'server':'payload must be valid json', 'code':'error'}), 200)
            response.headers["Content-Type"] = "application/json"
            return response
    except:
        response = make_response(json.dumps({'server':'payload must be valid json', 'code':'error'}), 200)
        response.headers["Content-Type"] = "application/json"
        return response


    provided = data.get("authorization", None)
    if ( provided == None ):
        response = make_response(json.dumps({'server':'you are unauthorized', 'code':'error'}), 200)
        response.headers["Content-Type"] = "application/json"
        return response

    if ( provided != auth ):
        response = make_response(json.dumps({'server':'you are unauthorized', 'code':'error'}), 200)
        response.headers["Content-Type"] = "application/json"
        return response

    func = request.environ.get('werkzeug.server.shutdown')
    if func is None:
        response = make_response(json.dumps({'server':'shutdown not allowed', 'code':'error'}), 200)
        response.headers["Content-Type"] = "application/json"
        return response

    func()
    response = make_response(json.dumps({'server':'shutting down...', 'code':'ok'}), 200)
    response.headers["Content-Type"] = "application/json"
    return response

if __name__ == "__main__":

    port = int(os.environ.get("PORT", 5000))
    database.create_all()

    for user in StoredUser.query.all():
        user.active = False
        database.session.add(user)
    database.session.commit()
    server.run(host="0.0.0.0", port=port)
