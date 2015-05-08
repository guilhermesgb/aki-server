from .. import app, db
from ..users import User
from ..chat_rooms_public import ChatRoom
from chat_presence import do_send_presence
from flask import make_response
from flask.ext.login import login_required, current_user, logout_user
from multiprocessing import Process
import json


@app.route('/inactive', methods=['POST'])
@login_required
def send_inactive():

    user_id = current_user.get_id()

    u = User.get_stored(user_id)
    u.active = False
    db.session.add(u)
    db.session.commit()

    User.get(user_id).set_terminate_timer()

    response = make_response(json.dumps({'server':'{} just became inactive'.format(user_id), 'code':'ok'}), 200)
    response.headers["Content-Type"] = "application/json"
    return response

    response.headers["Content-Type"] = "application/json"
    return response

@app.route('/skip', methods=['POST'])
@login_required
def send_skip():

    user_id = current_user.get_id()

    u = User.get_stored(user_id)
    u.active = False
    db.session.add(u)
    db.session.commit()

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

@app.route('/exit', methods=['POST'])
@login_required
def send_exit():

    user_id = current_user.get_id()

    u = User.get_stored(user_id)
    u.active = False
    db.session.add(u)
    db.session.commit()

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
