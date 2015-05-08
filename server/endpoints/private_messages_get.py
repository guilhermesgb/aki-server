from .. import app
from ..chat_rooms_private import PrivateChatRoom
from flask import make_response, request
#from flask.ext.login import login_required
import json, heapq


@app.route('/private_message/<current_id>/<user_id>/<int:amount>', methods=['GET'])
@app.route('/private_message/<current_id>/<user_id>', methods=['GET'])
#@login_required
def get_private_messages(current_id=None, user_id=None, amount=10):

    #this below was disabled because this method is no longer login_required
    #current_id = current_user.get_id()

    #TODO only allow this if current_user_id has mutual interest with user_id

    private_chat_room = PrivateChatRoom.get_chat(current_id, user_id)
    source = private_chat_room.messages

    after = request.args.get("next", None)
    if ( after ):
        try:
            after = int(after)
        except ValueError:
            response = make_response(json.dumps({'server':"\'next\' argument requires a number, cannot be {}".format(after), 'code':'error'}), 200)
            response.headers["Content-Type"] = "application/json"
            return response

        messages = get_msgs_after_tstamp(amount, source, after)
    else:
        messages = heapq.nsmallest(amount, source)

    next = None if ( len(messages) == 0 ) else messages[-1][0]
    remaining = len(get_msgs_after_tstamp(1, source, next)) if next else 0
    finished = remaining == 0

    messages = [ {
        "sender": x[1]["sender"],
        "message": x[1]["message"],
        "timestamp": str(int(x[0])).replace("L", "")
    } for x in messages ]

    response = {
        'server': '{} retrieved {} messages from chat {}'.format(current_id,
            len(messages), private_chat_room.cid),
        'code': 'ok',
        'messages': messages,
        'next': str(int(next)).replace("L", "") if next else None,
        'finished': finished
    }
    response['anonymous'] = private_chat_room.is_anonymous

    response = make_response(json.dumps(response), 200)
    response.headers["Content-Type"] = "application/json"
    return response
