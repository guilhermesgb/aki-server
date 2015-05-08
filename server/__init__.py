from flask import Flask, make_response
from flask.ext.login import LoginManager, UserMixin
from flask.ext.sqlalchemy import SQLAlchemy
import os, json, logging

logging.basicConfig(level=logging.DEBUG)

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", os.urandom(24))
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get(
    'DATABASE_URL', 'postgresql:///local_database')
app.config['UPLOADS_FOLDER'] = os.path.join(os.getcwd(), 'server', 'uploads')

login_manager = LoginManager(app)
db = SQLAlchemy(app)

from server.models import StoredUser, PrivateMessage,\
    MutualInterest, UploadedImage
from server.users import User
from server.chat_rooms_public import ChatRoom
from server.chat_rooms_private import PrivateChatRoom

import server.endpoints.index
import server.endpoints.chat_presence
import server.endpoints.chat_absence
import server.endpoints.chat_members
import server.endpoints.messages_get
import server.endpoints.messages_post
import server.endpoints.user_likes
import server.endpoints.user_mutuals
import server.endpoints.private_messages_get
import server.endpoints.private_messages_post
import server.endpoints.uploads


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
