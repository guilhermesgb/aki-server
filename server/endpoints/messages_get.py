from .. import app
from ..users import User
from ..chat_rooms_public import ChatRoom
from flask import make_response, request
from flask.ext.login import login_required, current_user
import json, heapq, copy


@app.route('/message/<int:amount>', methods=['GET'])
@app.route('/message', methods=['GET'])
@login_required
def get_messages(amount=10):

    user_id = current_user.get_id()
    chat_id = ChatRoom.at_chat(user_id)
    if ( chat_id ):

        source = ChatRoom.get_chat(chat_id).messages

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
            'server': '{} retrieved {} messages from chat {}'.format(user_id,
                len(messages), chat_id),
            'code': 'ok',
            'messages': messages,
            'next': str(int(next)).replace("L", "") if next else None,
            'finished': finished
        }

        u = User.get(user_id)
        if ( u.flag_mutual_interest ):
            response["update_mutual_interests"] = True
        response = make_response(json.dumps(response), 200)

    else:
        response = make_response(json.dumps({'server':'{} is not in a chat room'.format(user_id), 'code':'error'}), 200)

    response.headers["Content-Type"] = "application/json"
    return response

def get_msgs_after_tstamp(amount, source, after):

    messages = []

    all_m = copy.deepcopy(source)
    while ( len(all_m) > 0 and amount > 0 ):
        message = heapq.heappop(all_m)
        if ( message[0] <= after ):
            continue
        messages.append(message)
        amount = amount - 1

    return messages
