from .. import app, db
from ..users import User
from ..models import MutualInterest, PrivateMessage
from ..chat_rooms_private import PrivateChatRoom
from flask import make_response
from flask.ext.login import login_required, current_user
import json


@app.route('/mutual', methods=['GET'])
@login_required
def get_mutual():

    current_id = current_user.get_id()
    u = User.get(current_id)
    u.flag_mutual_interest = False

    results = []

    mutuals = MutualInterest.query.filter(
        MutualInterest.uid1 == current_id
    ).all()
    for mutual in mutuals:
        result = {}
        user = User.get_stored(mutual.uid2)
        if ( user ):
            result = {
                'uid': user.uid,
                'nickname': user.nickname,
                'gender': user.gender,
                'first_name': user.first_name,
                'full_name': user.full_name
            }
        else:
            result['uid'] = mutual.uid2
        private_chat_room = PrivateChatRoom.get_chat(current_id, mutual.uid2)
        result['anonymous'] = private_chat_room.is_anonymous[mutual.uid2]
        results.append(result)

    mutuals = MutualInterest.query.filter(
        MutualInterest.uid2 == current_id
    ).all()
    for mutual in mutuals:
        result = {}
        user = User.get_stored(mutual.uid1)
        if ( user ):
            result = {
                'uid': user.uid,
                'nickname': user.nickname,
                'gender': user.gender,
                'first_name': user.first_name,
                'full_name': user.full_name
            }
        else:
            result['uid'] = mutual.uid1
        private_chat_room = PrivateChatRoom.get_chat(current_id, mutual.uid1)
        result['anonymous'] = private_chat_room.is_anonymous[mutual.uid1]
        results.append(result)

    response = make_response(json.dumps({
        'server':'retrieved {}\'s mutual interests'.format(current_id),
        'mutuals': results,
        'code':'ok'
    }), 200)
    response.headers["Content-Type"] = "application/json"
    return response

@app.route('/mutual/<user_id>', methods=['DELETE'])
@login_required
def delete_mutual(user_id=None):

    current_id = current_user.get_id()

    if ( current_id == user_id ):
        response = make_response(json.dumps({'server':'a mutual between {} and oneself makes no sense'.format(user_id), 'code':'error'}), 200)
        response.headers["Content-Type"] = "application/json"
        return response

    mutuals = MutualInterest.query.filter(
        MutualInterest.uid1 == current_id,
        MutualInterest.uid2 == user_id
    ).all()
    for mutual in mutuals:
        db.session.delete(mutual)
    mutuals = MutualInterest.query.filter(
        MutualInterest.uid1 == user_id,
        MutualInterest.uid2 == current_id
    ).all()
    for mutual in mutuals:
        db.session.delete(mutual)

    if ( current_id < user_id ):
        cid = "chat-id" + current_id + user_id
    else:
        cid = "chat-id" + user_id + current_id
    for pmsg in PrivateMessage.query.filter(
      PrivateMessage.cid == cid).all():
        db.session.delete(pmsg)

    db.session.commit()

    u = User.get(user_id)
    if ( u ):
        u.flag_mutual_interest = True

    response = make_response(json.dumps({
        'server':'mutual interest between {} and {} removed'.format(current_id, user_id),
        'code':'ok'
    }), 200)
    response.headers["Content-Type"] = "application/json"
    return response
