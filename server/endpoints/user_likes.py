from .. import app
from ..users import User
from ..chat_rooms_public import ChatRoom
from flask import make_response
from flask.ext.login import login_required, current_user
import json


@app.route('/like/<user_id>', methods=['POST'])
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

@app.route('/dislike/<user_id>', methods=['POST'])
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
        response = make_response(json.dumps({'server':'{} cannot dislike oneself'.format(user_id), 'code':'error'}), 200)
        response.headers["Content-Type"] = "application/json"
        return response

    current_u.dislike(disliked_u)
    response = make_response(json.dumps({'server':'{} lost interest in {}'.format(current_id, user_id), 'code':'ok'}), 200)
    response.headers["Content-Type"] = "application/json"
    return response
