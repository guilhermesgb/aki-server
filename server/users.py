from server import db
from models import StoredUser, MutualInterest
from chat_rooms_public import ChatRoom
from chat_rooms_private import PrivateChatRoom
from request_utils import send_request
from flask.ext.login import UserMixin
from sqlalchemy.orm.exc import NoResultFound, MultipleResultsFound
from multiprocessing import Process
from threading import Timer, Lock
import os


class User(UserMixin):

    MAX_INACTIVE_TIME = 1 * 60 #10 minutes
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
            db.session.add(StoredUser(user_id, nickname, gender, \
                first_name, full_name))
            db.session.commit()
        except MultipleResultsFound:
            for user in StoredUser.query.all():
                db.session.remove(user)
            db.session.add(StoredUser(user_id, nickname, gender, \
                first_name, full_name))
            db.session.commit()

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
        db.session.add(u)
        db.session.commit()

        self.liked_users = []

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

                    db.session.add(MutualInterest(uid1, uid2))
                    db.session.commit()

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
        return StoredUser.query.filter(StoredUser.uid == uid).first()

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

    private_chat_room = PrivateChatRoom.get_chat(uid1, uid2)

    user_data = {
        "action" : "com.lespi.aki.receivers.INCOMING_MUTUAL_INTEREST_UPDATE",
        "uid1": {
            "uid": uid1,
            "anonymous": private_chat_room.is_anonymous[uid1]
        },
        "uid2": {
            "uid": uid2,
            "anonymous": private_chat_room.is_anonymous[uid2]
        }
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

