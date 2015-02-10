from flask import Flask, make_response, request, send_from_directory
from flask.ext.login import LoginManager, login_user, logout_user,\
login_required, current_user, UserMixin
from flask.ext.sqlalchemy import SQLAlchemy, Session
from sqlalchemy.orm.exc import NoResultFound, MultipleResultsFound
from werkzeug import secure_filename

from request_utils import send_request

from multiprocessing import Process, Pool
from threading import Timer, Lock
import os, json, logging, math, sys, uuid, heapq, time, copy

logging.basicConfig(level=logging.DEBUG)

server = Flask(__name__)
server.secret_key = os.environ.get("SECRET_KEY", os.urandom(24))
server.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get(
    'DATABASE_URL', 'postgresql:///local_database')
server.config['UPLOADS_FOLDER'] = 'uploads'

login_manager = LoginManager(server)
database = SQLAlchemy(server)


class StoredUser(database.Model):

    __tablename__ = 'person'
    id = database.Column(database.Integer, primary_key=True)
    uid = database.Column(database.String(20), unique=True)
    nickname = database.Column(database.String(50))
    gender = database.Column(database.String(50))
    first_name = database.Column(database.String(50))
    full_name = database.Column(database.String(50))
    active = database.Column(database.Boolean)

    def __init__(self, user_id, nickname, gender, \
      first_name, full_name, active=False):
        self.uid = user_id
        self.nickname = nickname
        self.gender = gender
        self.first_name = first_name
        self.full_name = full_name
        self.active = active

    def __repr__(self):
        return "<Username {}>".format(self.uid)

class User(UserMixin):

    MAX_INACTIVE_TIME = 10 * 60 #10 minutes
    users = {}

    def __init__(self, user_id, nickname, gender, \
      first_name, full_name, anonymous, active=True):
        self.uid = user_id
        self.anonymous_setting = anonymous
        self.active = active
        self.skipped_chats = []
        self.compromised_chats = []
        self.terminate_timer = None
        self.liked_users = []
        self.lock = Lock()
        self.flag_mutual_interest = False

        try:
            StoredUser.query.filter(StoredUser.uid == user_id).one()
        except NoResultFound:
            database.session.add(StoredUser(user_id, nickname, gender, \
                first_name, full_name))
            database.session.commit()
        except MultipleResultsFound:
            for user in StoredUser.query.all():
                database.session.remove(user)
            database.session.add(StoredUser(user_id, nickname, gender, \
                first_name, full_name))
            database.session.commit()

        if ( not user_id in User.users ):
            User.users[user_id] = self

    def is_authenticated(self):
        return True

    def is_active(self):
        return True

    #This method is necessary for the UserMixin
    def is_anonymous(self):
        return False

    def get_id(self):
        return unicode(self.uid)

    def is_currently_anonymous(self):
        return self.anonymous_setting

    def set_anonymous(self, anonymous):
        self.anonymous_setting = anonymous

    def terminate(self):
        u = User.get_stored(self.uid)
        u.active = False
        database.session.add(u)
        database.session.commit()

        u_ = User.get(user_id)
        u_.liked_users = []

        chat_id = ChatRoom.at_chat(self.uid)
        if ( chat_id ):
            chat_room = ChatRoom.get_chat(chat_id)
            if ( chat_room ):
                if ( not self.is_currently_anonymous() ):
                    self.compromised_chats.extend(chat_room.ids)
                    self.compromised_chats = list(set(self.compromised_chats))
                chat_room.remove_user(self.uid)

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
#        u = User.users.get(uid, None)
#        if ( u != None ):
#            return u.do_get_stored()
#        return None
        return StoredUser.query.filter(StoredUser.uid == uid).first()

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
        if ( len(self.members.keys()) != 0 ):
            self.update_center_and_radius()
        else:
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

class PrivateMessage(database.Model):

    __tablename__ = "private_message"
    id = database.Column(database.Integer, primary_key=True)
    cid = database.Column(database.String(50))
    timestamp = database.Column(database.String(50))
    sender_id = database.Column(database.String(50))
    message = database.Column(database.String(50))

    def __init__(self, cid, timestamp, sender_id, message):
        self.cid = cid
        self.timestamp = timestamp
        self.sender_id = sender_id
        self.message = message

    def __repr__(self):
        return "PrivateMessage from {}".format(self.sender_id)

class PrivateChatRoom:

    chats = {}

    def __init__(self, uid1, uid2):
        if ( uid1 < uid2 ): 
            self.cid  = "chat-" + uid1 + uid2
        else:
            self.cid  = "chat-" + uid2 + uid1
        self.is_anonymous = {
             uid1 : None,
             uid2 : None
        }
        self.messages = []
        for pmsg in PrivateMessage.query.filter(
          PrivateMessage.cid == self.cid).all():
            self.add_message(pmsg.sender_id, pmsg.message, \
              int(pmsg.timestamp), False)
        PrivateChatRoom.chats[self.cid] = self

    def add_message(self, sender_id, message, timestamp, persist_now=False):
        heapq.heappush(self.messages, (timestamp, {
            "sender": sender_id,
            "message": message
        }))
        if ( persist_now ):
            timestamp = str(int(timestamp)).replace("L", "")
            pmsg = PrivateMessage(self.cid, timestamp, sender_id, message)
            database.session.add(pmsg)
            database.session.commit()
        return timestamp

    def set_anonymous(self, sender_id, anonymous):
        self.is_anonymous[sender_id] = anonymous

    @staticmethod
    def get_chat(uid1, uid2):
        if ( uid1 < uid2 ): 
            chat_id  = "chat-" + uid1 + uid2
        else:
            chat_id  = "chat-" + uid2 + uid1
        return PrivateChatRoom.chats.get(chat_id, PrivateChatRoom(uid1, uid2))

class MutualInterest(database.Model):

    __tablename__ = 'mutual'
    id = database.Column(database.Integer, primary_key=True)
    uid1 = database.Column(database.String(50))
    uid2 = database.Column(database.String(50))

    def __init__(self, uid1, uid2):
        self.uid1 = uid1
        self.uid2 = uid2

    def __repr__(self):
        return "<Mutual {} & {}>".format(self.uid1, self.uid2)

class UploadedImage(database.Model):

    __tablename__ = "uploaded_image"
    id = database.Column(database.Integer, primary_key=True)
    name = database.Column(database.String(50))
    blob = database.Column(database.LargeBinary())

    def __init__(self, name, blob):
        self.name = name
        self.blob = blob

    def __repr__(self):
        return "UploadedImage {}".format(self.name)


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
            'liked': u_.liked_users,
            'skipped': u_.skipped_chats,
            'compromised': u_.compromised_chats
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
        if ( len(first_name) > 50 ):
            first_name = first_name[:50]
        user_data["first_name"] = first_name

    full_name = data.get('full_name', None)
    if ( full_name != None ):
        if ( len(full_name) > 50 ):
            full_name = full_name[:50]
        user_data["full_name"] = full_name

    gender = data.get('gender', None)
    if ( gender != None ):
        user_data["gender"] = gender

    nickname = data.get('nickname', None)
    if ( nickname != None ):
        if ( len(nickname) > 50 ):
            nickname = nickname[:50]
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
        print "location", location
        location["lat"] = float(location["lat"])
        location["long"] = float(location["long"])

    if ( current_user.is_authenticated() ):
        logging.info("You are already authenticated")
        if ( current_user.get_id() != user_id ):
            logging.info("But you are "+current_user.get_id()+", not "+user_id)
            response = make_response(json.dumps({'server':'presence fail (you are someone else)', 'code':'error'}), 200)
        else:
            u = User.get_stored(user_id)
            u.nickname = nickname
            u.gender = gender
            u.first_name = first_name
            u.full_name = full_name
            u.active = True
            database.session.add(u)
            database.session.commit()
            u_ = User.get(user_id)
            u_.set_anonymous(anonymous)
            u_.cancel_terminate_timer()
            logging.info("Presence sent ok")
            chat_id, chat_ids = ChatRoom.assign_chat(user_id, location)
            should_not_be_anonymous = False
            for cid in chat_ids:
                if ( cid in u_.compromised_chats ):
                    user_data['anonymous'] = False
                    should_not_be_anonymous = True
                    break
            chat_room = ChatRoom.get_chat(chat_id)
            if ( chat_room ):
                chat_room.update_user(user_id, user_data)

            p = Process(target=do_send_presence,
                args=(chat_ids, user_data))
            p.daemon = True
            p.start()

            response = {
                'server':'presence sent (already authenticated)',
                'chat_room': chat_id,
                'code':'ok'
            }
            if ( u_.flag_mutual_interest ):
                response["update_mutual_interests"] = True
            if ( should_not_be_anonymous ):
                response["should_not_be_anonymous"] = True
            response = make_response(json.dumps(response), 200)
    else:

        User(user_id, nickname, gender, first_name, full_name, anonymous)
        u = User.get_stored(user_id)
        if ( login_user(User.get(user_id), remember=True) ):
            u.active = True
            database.session.add(u)
            database.session.commit()
            u_ = User.get(user_id)
            u_.set_anonymous(anonymous)
            u_.cancel_terminate_timer()
            logging.info("Presence sent ok (by logging)")
            chat_id, chat_ids = ChatRoom.assign_chat(user_id, location)
            should_not_be_anonymous = False
            for cid in chat_ids:
                if ( cid in u_.compromised_chats ):
                    user_data['anonymous'] = False
                    should_not_be_anonymous = True
                    break
            chat_room = ChatRoom.get_chat(chat_id)
            if ( chat_room ):
                chat_room.update_user(user_id, user_data)

            p = Process(target=do_send_presence,
                args=(chat_ids, user_data))
            p.daemon = True
            p.start()

            response = {
                'server':'presence sent (just authenticated)',
                'chat_room': chat_id,
                'code':'ok',
                'timestamp':str(int(time.time() * 1000000)).replace("L", "")
            }
            if ( u_.flag_mutual_interest ):
                response["update_mutual_interests"] = True
            if ( should_not_be_anonymous ):
                response["should_not_be_anonymous"] = True
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
        if ( chat_room ):
            u_.skipped_chats.extend(chat_room.ids)
            if ( not u_.is_currently_anonymous() ):
                u_.compromised_chats.extend(chat_room.ids)
                u_.compromised_chats = list(set(u_.compromised_chats))
            chat_room.remove_user(user_id)

        user_data = {
            "from": user_id,
            "anonymous": True,
            "location": "unknown"
        }

        p = Process(target=do_send_presence,
            args=(chat_room.ids, user_data))
        p.daemon = True
        p.start()
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
        chat_room = ChatRoom.get_chat(chat_id)
        if ( chat_room ):
            u_.skipped_chats.extend(chat_room.ids)
            if ( not u_.is_currently_anonymous() ):
                u_.compromised_chats.extend(chat_room.ids)
                u_.compromised_chats = list(set(u_.compromised_chats))
            chat_room.remove_user(user_id)

        user_data = {
            "from": user_id,
            "anonymous": True,
            "location": "unknown"
        }

        p = Process(target=do_send_presence,
            args=(chat_room.ids, user_data))
        p.daemon = True
        p.start()
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

    message = message[:50]

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
def send_like(user_id=None):

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
def send_dislike(user_id=None):

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
    ).all()
    for mutual in mutuals:
        user = User.get_stored(mutual.uid2)
        if ( user ):
            results.append({
                'uid': user.uid,
                'nickname': user.nickname,
                'gender': user.gender,
                'first_name': user.first_name,
                'full_name': user.full_name
            })
        else:
            results.append({
                'uid': mutual.uid2
            })
    mutuals = MutualInterest.query.filter(
        MutualInterest.uid2 == current_id
    ).all()
    for mutual in mutuals:
        user = User.get_stored(mutual.uid1)
        if ( user ):
            results.append({
                'uid': user.uid,
                'nickname': user.nickname,
                'gender': user.gender,
                'first_name': user.first_name,
                'full_name': user.full_name
            })
        else:
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

@server.route('/mutual/<user_id>', methods=['DELETE'])
@login_required
def delete_mutual(user_id=None):

    current_id = current_user.get_id()

    mutuals = MutualInterest.query.filter(
        MutualInterest.uid1 == current_id,
        MutualInterest.uid2 == user_id
    ).all()
    for mutual in mutuals:
        database.session.delete(mutual)
    mutuals = MutualInterest.query.filter(
        MutualInterest.uid1 == user_id,
        MutualInterest.uid2 == current_id
    ).all()
    for mutual in mutuals:
        database.session.delete(mutual)

    if ( current_id < user_id ):
        cid = "chat-id" + current_id + user_id
    else:
        cid = "chat-id" + user_id + current_id
    for pmsg in PrivateMessage.query.filter(
      PrivateMessage.cid == cid).all():
        database.session.delete(pmsg)

    database.session.commit()

    u = User.get(user_id)
    if ( u ):
        u.flag_mutual_interest = True

    response = make_response(json.dumps({
        'server':'mutual interest between {} and {} removed'.format(current_id, user_id),
        'code':'ok'
    }), 200)
    response.headers["Content-Type"] = "application/json"
    return response

def warn_about_private_message(sender_id, chat_id, anonymous):

    headers = {
        "X-Parse-Application-Id": os.environ.get("PARSE_APPLICATION_ID", None),
        "X-Parse-REST-API-Key": os.environ.get("PARSE_REST_API_KEY", None),
        "Content-Type":"application/json"
    }

    data = {
        "from": sender_id,
        "action": "com.lespi.aki.receivers.INCOMING_PRIVATE_MESSAGE",
    }

    if ( anonymous != None ):
        data["anonymous"] = anonymous

    payload = {
        "where": {
            "channels": {
                "$in": [ chat_id ]
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


@server.route('/private_message/<user_id>', methods=['POST'])
@login_required
def send_private_message(user_id=None):

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

    message = message[:50]

    current_id = current_user.get_id()
    #TODO only allow this if current_user_id has mutual interest with user_id

    private_chat_room = PrivateChatRoom.get_chat(current_id, user_id)
    private_chat_room.add_message(current_id, message, \
      (time.time() * 1000000), True)

    anonymous = data.get('anonymous', None)
    if ( anonymous != None ):
        private_chat_room.set_anonymous(current_id, anonymous)

    p = Process(target=warn_about_private_message,
      args=(current_user.get_id(), private_chat_room.cid, anonymous))
    p.daemon = True
    p.start()

    response = make_response(json.dumps({'server':'message sent', 'code':'ok'}), 200)
    response.headers["Content-Type"] = "application/json"
    return response

@server.route('/private_message/<user_id>/<int:amount>', methods=['GET'])
@server.route('/private_message/<user_id>', methods=['GET'])
@login_required
def get_private_messages(user_id=None, amount=10):

    current_id = current_user.get_id()
    #TODO only allow this if current_user_id has mutual interest with user_id

    private_chat_room = PrivateChatRoom.get_chat(current_id, user_id)
    source = private_chat_room.messages

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
        'server': '{} retrieved {} messages from chat {}'.format(current_id,
            len(messages), private_chat_room.cid),
        'code': 'ok',
        'messages': messages,
        'next': str(int(next)).replace("L", "") if next else None,
        'finished': finished
    }

    anonymous = {}
    for uid in private_chat_room.is_anonymous:
        if ( private_chat_room.is_anonymous[uid] != None ):
            anonymous[uid] = private_chat_room.is_anonymous[uid]
    response['anonymous'] = anonymous

    response = make_response(json.dumps(response), 200)
    response.headers["Content-Type"] = "application/json"
    return response

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1] in ['png', 'jpg', 'jpeg']

@server.route('/upload', methods=['POST'])
@login_required
def upload_file():

    _file = request.files['filename']
    if ( _file and allowed_file(_file.filename) ):
        filename = secure_filename(_file.filename)

        if ( current_user.get_id() in filename ):
            path = os.path.join(server.config['UPLOADS_FOLDER'], filename)
            _file.save(path)
            _file = open(path, 'r')
            _stored = UploadedImage(filename, _file.read())
            _file.close()
            database.session.add(_stored)
            database.session.commit()
            response = make_response(json.dumps({'server':filename + ' uploaded!', 'code':'ok'}), 200)
        else:
            response = make_response(json.dumps({'server':'you don\'t have permission to upload this file!', 'code':'error'}), 200)
    else:
        response = make_response(json.dumps({'server':filename + ' could not be uploaded!', 'code':'error'}), 200)
    response.headers["Content-Type"] = "application/json"
    return response

@server.route('/upload/<filename>', methods=['GET', 'HEAD'])
@login_required
def serve_uploaded_file(filename):
    return send_from_directory(server.config['UPLOADS_FOLDER'], filename)

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

    for upload in UploadedImage.query.all():
        _file = open(os.path.join(server.config['UPLOADS_FOLDER'], upload.name), 'w')
        _file.write(upload.blob)
        _file.close()

    server.run(host="0.0.0.0", port=port)
