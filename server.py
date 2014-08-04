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

@server.route('/presence/<username>', methods=['POST'])
def send_presence(username):

    if ( current_user.is_authenticated() ):
        logging.info("You are already authenticated")
        if ( current_user.get_id() != username ):
            logging.info("But you are "+current_user.get_id()+", not "+username)
            response = make_response(json.dumps({'server':'presence fail (you are someone else)', 'code':'error'}), 200)
        else:
            logging.info("Presence sent ok")
            response = make_response(json.dumps({'server':'presence sent (already authenticated)', 'code':'ok'}), 200)
    else:

        User(username)
        u = User.get_stored(username)
        if ( login_user(User.get(username), remember=True) ):
            u.taken = True
            database.session.add(u)
            database.session.commit()
            logging.info("Presence sent ok (by logging)")
            response = make_response(json.dumps({'server':'presence sent (just authenticated)', 'code':'ok'}), 200)
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

def do_send_message(sender, message):

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
            "chatroom"
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
        response = make_response(json.dumps({'server':'message cannot be ommitted!', 'code':'error'}), 200)
        response.headers["Content-Type"] = "application/json"
        return response

    p = Process(target=do_send_message,
        args=(current_user.get_id(), message))
    p.daemon = True
    p.start()

    logging.info("just started ~send_message~ process")
    response = make_response(json.dumps({'server':'message sent', 'code':'ok'}), 200)
    response.headers["content-type"] = "application/json"
    return response

@server.route('/chat', methods=['POST'])
@login_required
def enter_chat():

    username = current_user.get_id()
    chat_room = "chat_room"

    status = {
        'server': '{} is in chat room {}'.format(username, chat_room),
        'code': 'ok',
        'chat_room': chat_room
    }

    response = make_response(json.dumps(status), 200)
    response.headers["Content-Type"] = "application/json"
    return response

if __name__ == "__main__":

    port = int(os.environ.get("PORT", 5000))
    database.create_all()

    for user in StoredUser.query.all():
        user.taken = False
        database.session.add(user)
    database.session.commit()
    server.run(host="0.0.0.0", port=port)
