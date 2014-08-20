from flask import Flask, make_response, request
from flask.ext.login import LoginManager, login_user, logout_user,\
login_required, current_user, UserMixin
from flask.ext.sqlalchemy import SQLAlchemy, Session
from sqlalchemy.orm.exc import NoResultFound, MultipleResultsFound

from request_utils import send_request

from multiprocessing import Process
import os, json, logging

logging.basicConfig(level=logging.DEBUG)

server = Flask(__name__)
server.secret_key = os.environ.get("SECRET_KEY", os.urandom(24))
server.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get(
    'DATABASE_URL', 'postgresql:///local_database')

login_manager = LoginManager(server)
database = SQLAlchemy(server)

class StoredUser(database.Model):

    __tablename__ = 'person'
    id = database.Column(database.Integer, primary_key=True)
    uid = database.Column(database.String(20), unique=True)
    taken = database.Column(database.Boolean)

    def __init__(self, username, taken=False):
        self.uid = username
        self.taken = taken

    def __repr__(self):
        return "<Username {}>".format(self.uid)

class User(UserMixin):

    users = {}

    def __init__(self, username, active=True):

        self.uid = username
        self.active = active

        try:
            StoredUser.query.filter(StoredUser.uid == username).one()
        except NoResultFound:
            database.session.add(StoredUser(username))
            database.session.commit()
        except MultipleResultsFound:
            for user in StoredUser.query.all():
                database.session.remove(user)
            database.session.add(StoredUser(username))
            database.session.commit()

        if ( not username in User.users ):
            User.users[username] = self

    def is_authenticated(self):
        return True

    def is_active(self):
        return True

    def is_anonymous(self):
        return False

    def get_id(self):
        return unicode(self.uid)

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

@login_manager.user_loader
def load_user(username):
    return User.get(username)

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
    for user in User.users.keys():
        u = User.get_stored(user)
        users.append({
            'username' : u.uid,
            'status' : 'active' if u.taken else 'inactive'
        })

    response = make_response(json.dumps({
        'server':'alive',
        'users': users
    }), 200)
    response.headers["Content-Type"] = "application/json"
    return response

@server.route('/presence', methods=['GET'])
def get_presence():

    status = {
        'server' : 'you must send presence',
        'code' : 'error'
    }

    if ( current_user.is_authenticated() ):
        status['server'] = 'you are {}'.format(current_user.get_id())
        status['code'] = 'ok'
        status['username'] = current_user.get_id()

    response = make_response(json.dumps(status), 200)
    response.headers["Content-Type"] = "application/json"
    return response

def do_send_presence(chat_room, user_data):

    database.session = database.create_scoped_session()

    headers = {
        "X-Parse-Application-Id": os.environ.get("PARSE_APPLICATION_ID", None),
        "X-Parse-REST-API-Key": os.environ.get("PARSE_REST_API_KEY", None),
        "Content-Type":"application/json"
    }

    user_data["action"] = "com.lespi.aki.receivers.INCOMING_USER_INFO_UPDATE"

    payload = {
        "channels": [
            chat_room
        ], 
        "data" : user_data
    }

    response = send_request('POST', "https://api.parse.com/1/push",
         payload=payload, headers=headers) 

    if ( response["success"] ):
        logging.info("Message sent to Parse push notifications system")
    else:
        logging.info("Cannot send message to Parse push notifications system")


@server.route('/presence/<username>', methods=['POST'])
def send_presence(username):

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

    user_data["from"] = username
    user_data["anonymous"] = anonymous
    user_data["location"] = location

    if ( current_user.is_authenticated() ):
        logging.info("You are already authenticated")
        if ( current_user.get_id() != username ):
            logging.info("But you are "+current_user.get_id()+", not "+username)
            response = make_response(json.dumps({'server':'presence fail (you are someone else)', 'code':'error'}), 200)
        else:
            logging.info("Presence sent ok")
            chat_room = get_chat()

            p = Process(target=do_send_presence,
                args=(chat_room, user_data))
            p.daemon = True
            p.start()

            response = make_response(json.dumps({
                           'server':'presence sent (already authenticated)',
                           'chat_room': chat_room,
                           'code':'ok'
                       }), 200)
    else:

        User(username)
        u = User.get_stored(username)
        if ( login_user(User.get(username), remember=True) ):
            u.taken = True
            database.session.add(u)
            database.session.commit()
            logging.info("Presence sent ok (by logging)")
            chat_room = get_chat()

            p = Process(target=do_send_presence,
                args=(chat_room, user_data))
            p.daemon = True
            p.start()

            response = make_response(json.dumps({
                           'server':'presence sent (just authenticated)',
                           'chat_room': chat_room,
                           'code':'ok'
                       }), 200)
        else:
            logging.info("Presence sent not ok (login failed)")
            response = make_response(json.dumps({'server':'presence fail (login fail)', 'code':'error'}), 200)

    response.headers["content-type"] = "application/json"
    return response

@server.route('/leave', methods=['POST'])
@login_required
def send_leave():

    username = current_user.get_id()

    if logout_user():
        u = User.get_stored(username)
        u.taken = False
        database.session.add(u)
        database.session.commit()
        response = make_response(json.dumps({'server':'{} just left'.format(username), 'code':'ok'}), 200)
    else:
        response = make_response(json.dumps({'server':'leaving failed somehow', 'code':'error'}), 200)

    response.headers["Content-Type"] = "application/json"
    return response

def do_send_message(sender, chat_room, message):

    database.session = database.create_scoped_session()

    headers = {
        "X-Parse-Application-Id": os.environ.get("PARSE_APPLICATION_ID", None),
        "X-Parse-REST-API-Key": os.environ.get("PARSE_REST_API_KEY", None),
        "Content-Type":"application/json"
    }

    data = {
        "from": sender,
        "message": message,
        "action": "com.lespi.aki.receivers.INCOMING_MESSAGE",
    }

    payload = {
        "channels": [
            chat_room
        ],      
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

    message = data.get('message', None)

    if ( message == None ):
        response = make_response(json.dumps({'server':'message field cannot be ommitted!', 'code':'error'}), 200)
        response.headers["Content-Type"] = "application/json"
        return response

    chat_room = data.get('chat_room', None)

    if ( chat_room == None ):
        response = make_response(json.dumps({'server':'chat_room field cannot be ommitted!', 'code':'error'}), 200)
        response.headers["Content-Type"] = "application/json"
        return response

    p = Process(target=do_send_message,
        args=(current_user.get_id(), chat_room, message))
    p.daemon = True
    p.start()

    logging.info("just started ~send_message~ process")
    response = make_response(json.dumps({'server':'message sent', 'code':'ok'}), 200)
    response.headers["content-type"] = "application/json"
    return response

def get_chat():
    # for now simply returning global chat room (id: chat_room)
    return "chat_room_for_me"

if __name__ == "__main__":

    port = int(os.environ.get("PORT", 5000))
    database.create_all()

    for user in StoredUser.query.all():
        user.taken = False
        database.session.add(user)
    database.session.commit()
    server.run(host="0.0.0.0", port=port)
