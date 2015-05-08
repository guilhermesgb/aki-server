from .. import app
from ..users import User
from ..chat_rooms_public import ChatRoom
from ..request_utils import send_request
from flask import make_response, request
from flask.ext.login import login_required, current_user
from multiprocessing import Process
import os, json, copy


@app.route('/message', methods=['POST'])
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

            response = make_response(json.dumps({'server':'message sent', 'code':'ok'}), 200)
            response.headers["content-type"] = "application/json"
            return response
    else:
        response = make_response(json.dumps({'server':current_user.get_id() + ' is not in a chat_room!', 'code':'error'}), 200)
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
