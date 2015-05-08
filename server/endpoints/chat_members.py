from .. import app
from ..chat_rooms_public import ChatRoom
from flask import make_response
from flask.ext.login import login_required, current_user
import json


@app.route('/members', methods=['GET'])
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
