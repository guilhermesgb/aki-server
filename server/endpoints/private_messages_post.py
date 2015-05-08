from .. import app
from ..users import User
from ..chat_rooms_private import PrivateChatRoom
from ..request_utils import send_request
from flask import make_response, request
from flask.ext.login import login_required, current_user
from multiprocessing import Process
import os, json, time


@app.route('/private_message/<user_id>', methods=['POST'])
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

    current_id = current_user.get_id()

    #TODO only allow this if current_user_id has mutual interest with user_id

    private_chat_room = PrivateChatRoom.get_chat(current_id, user_id)

    action = "com.lespi.aki.receivers.INCOMING_PRIVATE_MESSAGE"
    message = data.get('message', None)
    if ( message != None ):
        private_chat_room.add_message(current_id, message, \
          (time.time() * 1000000), True)
    else:
        action = "com.lespi.aki.receivers.INCOMING_MATCH_INFO_UPDATE"

    anonymous = data.get('anonymous', None)
    if ( anonymous != None ):
        private_chat_room.set_anonymous(current_id, anonymous)

    p = Process(target=warn_about_private_message,
      args=(current_id, private_chat_room.cid, anonymous, action, message))
    p.daemon = True
    p.start()

    response = make_response(json.dumps({'server':'message sent', 'code':'ok'}), 200)
    response.headers["Content-Type"] = "application/json"
    return response

def warn_about_private_message(sender_id, chat_id, anonymous, action, message):

    headers = {
        "X-Parse-Application-Id": os.environ.get("PARSE_APPLICATION_ID", None),
        "X-Parse-REST-API-Key": os.environ.get("PARSE_REST_API_KEY", None),
        "Content-Type":"application/json"
    }

    data = {
        "from": sender_id,
        "action": action,
        "message": message
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
