from .. import app, db
from ..users import User
from ..chat_rooms_public import ChatRoom
from ..request_utils import send_request
from flask import make_response, request
from flask.ext.login import login_user, current_user
from multiprocessing import Process
import os, json, time


@app.route('/presence', methods=['GET'])
def get_presence():

    status = {
        'server' : 'you must send presence',
        'code' : 'ok',
        'user_id' : None
    }

    if ( current_user.is_authenticated() ):
        status['server'] = 'you are {}'.format(current_user.get_id())
        status['code'] = 'ok'
        status['user_id'] = current_user.get_id()

    response = make_response(json.dumps(status), 200)
    response.headers["Content-Type"] = "application/json"
    return response

@app.route('/presence/<user_id>', methods=['POST'])
def send_presence(user_id):

    data = request.json
    user_data = {}

    first_name = data.get('first_name', None)
    if ( first_name != None ):
        if ( len(first_name) > 50 ):
            first_name = first_name[:50]
        user_data["first_name"] = first_name

    full_name = data.get('full_name', None)
    if ( full_name != None ):
        if ( len(full_name) > 50 ):
            full_name = full_name[:50]
        user_data["full_name"] = full_name

    gender = data.get('gender', None)
    if ( gender != None ):
        user_data["gender"] = gender

    nickname = data.get('nickname', None)
    if ( nickname != None ):
        if ( len(nickname) > 13 ):
            nickname = nickname[:13]
        user_data["nickname"] = nickname

    anonymous = data.get('anonymous', None)
    if ( anonymous == None ):
        response = make_response(json.dumps({'server':'anonymous field cannot be ommitted!', 'code':'error'}), 200)
        response.headers["Content-Type"] = "application/json"
        return response

    location = data.get('location', None)
    if ( location == None ):
        response = make_response(json.dumps({'server':'location field cannot be ommitted!', 'code':'error'}), 200)
        response.headers["Content-Type"] = "application/json"
        return response

    user_data["from"] = user_id
    user_data["anonymous"] = anonymous
    user_data["location"] = location

    if ( location != "unknown" ):
        print "location", location
        location["lat"] = float(location["lat"])
        location["long"] = float(location["long"])

    if ( current_user.is_authenticated() ):
        if ( current_user.get_id() != user_id ):
            response = make_response(json.dumps({'server':'presence fail (you are someone else)', 'code':'error'}), 200)
        else:
            u = User.get_stored(user_id)
            u.nickname = nickname
            u.gender = gender
            u.first_name = first_name
            u.full_name = full_name
            u.active = True
            db.session.add(u)
            db.session.commit()
            u_ = User.get(user_id)
            u_.set_anonymous(anonymous)
            u_.cancel_terminate_timer()
            chat_id, chat_ids = ChatRoom.assign_chat(user_id, location)
            should_not_be_anonymous = False
            for cid in chat_ids:
                if ( cid in u_.compromised_chats ):
                    user_data['anonymous'] = False
                    should_not_be_anonymous = True
                    break
            chat_room = ChatRoom.get_chat(chat_id)
            if ( chat_room ):
                chat_room.update_user(user_id, user_data)

            p = Process(target=do_send_presence,
                args=(chat_ids, user_data))
            p.daemon = True
            p.start()

            response = {
                'server':'presence sent (already authenticated)',
                'chat_room': chat_id,
                'code':'ok'
            }
            if ( u_.flag_mutual_interest ):
                response["update_mutual_interests"] = True
            if ( should_not_be_anonymous ):
                response["should_not_be_anonymous"] = True
            response = make_response(json.dumps(response), 200)
    else:

        User(user_id, nickname, gender, first_name, full_name, anonymous)
        u = User.get_stored(user_id)
        if ( login_user(User.get(user_id), remember=True) ):
            u.active = True
            db.session.add(u)
            db.session.commit()
            u_ = User.get(user_id)
            u_.set_anonymous(anonymous)
            u_.cancel_terminate_timer()
            chat_id, chat_ids = ChatRoom.assign_chat(user_id, location)
            should_not_be_anonymous = False
            for cid in chat_ids:
                if ( cid in u_.compromised_chats ):
                    user_data['anonymous'] = False
                    should_not_be_anonymous = True
                    break
            chat_room = ChatRoom.get_chat(chat_id)
            if ( chat_room ):
                chat_room.update_user(user_id, user_data)

            p = Process(target=do_send_presence,
                args=(chat_ids, user_data))
            p.daemon = True
            p.start()
            do_send_presence(chat_ids, user_data)

            response = {
                'server':'presence sent (just authenticated)',
                'chat_room': chat_id,
                'code':'ok',
                'timestamp':str(int(time.time() * 1000000)).replace("L", "")
            }
            if ( u_.flag_mutual_interest ):
                response["update_mutual_interests"] = True
            if ( should_not_be_anonymous ):
                response["should_not_be_anonymous"] = True
            response = make_response(json.dumps(response), 200)
        else:
            response = make_response(json.dumps({'server':'presence fail (login fail)', 'code':'error'}), 200)

    response.headers["content-type"] = "application/json"
    return response

def do_send_presence(chat_ids, user_data):

    if ( len(chat_ids) == 0 ):
        return

    headers = {
        "X-Parse-Application-Id": os.environ.get("PARSE_APPLICATION_ID", None),
        "X-Parse-REST-API-Key": os.environ.get("PARSE_REST_API_KEY", None),
        "Content-Type":"application/json"
    }

    user_data["action"] = "com.lespi.aki.receivers.INCOMING_USER_INFO_UPDATE"

    payload = {
        "channels": chat_ids, 
        "data" : user_data
    }

    response = send_request('POST', "https://api.parse.com/1/push",
         payload=payload, headers=headers)

@app.route('/stealth/<user_id>', methods=['POST'])
def send_stealth_presence(user_id):

    if ( current_user.is_authenticated() ):
        if ( current_user.get_id() != user_id ):
            response = make_response(json.dumps({'server':'stealth presence fail (you are someone else)', 'code':'error'}), 200)
        else:
            _u = User.get_stored(user_id)
            _u.active = False
            db.session.add(_u)
            db.session.commit()
            u = User.get(user_id)
            response = {
                'server':'stealth presence sent (already authenticated)',
                'code':'ok'
            }
            if ( u.flag_mutual_interest ):
                response["update_mutual_interests"] = True
            response = make_response(json.dumps(response), 200)
    else:

        u = User(user_id, active=False)
        if ( login_user(u, remember=True) ):
            _u = User.get_stored(user_id)
            _u.active = False
            db.session.add(_u)
            db.session.commit()
            response = {
                'server':'stealth presence sent (just authenticated)',
                'code':'ok'
            }
            if ( u.flag_mutual_interest ):
                response["update_mutual_interests"] = True
            response = make_response(json.dumps(response), 200)
        else:
            response = make_response(json.dumps({'server':'stealth presence fail (login fail)', 'code':'error'}), 200)

    response.headers["content-type"] = "application/json"
    return response
