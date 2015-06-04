from .. import app
from ..users import User
from ..chat_rooms_public import ChatRoom
from flask import make_response
import json


@app.route('/', methods=['GET', 'POST'])
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
            "tags": chat_room.tags,
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
