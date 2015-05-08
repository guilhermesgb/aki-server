from server import db
from models import PrivateMessage
import heapq


class PrivateChatRoom:

    chats = {}

    def __init__(self, uid1, uid2):
        if ( uid1 < uid2 ): 
            cid  = "chat-" + uid1 + uid2
        else:
            cid  = "chat-" + uid2 + uid1
        self.cid = cid
        self.is_anonymous = {
             uid1 : None,
             uid2 : None
        }
        self.messages = []
        for pmsg in PrivateMessage.query.filter(
          PrivateMessage.cid == self.cid).all():
            self.add_message(pmsg.sender_id, pmsg.message, \
              int(pmsg.timestamp), False)
        PrivateChatRoom.chats[self.cid] = self

    def add_message(self, sender_id, message, timestamp, persist_now=False):
        heapq.heappush(self.messages, (timestamp, {
            "sender": sender_id,
            "message": message
        }))
        if ( persist_now ):
            timestamp = str(int(timestamp)).replace("L", "")
            pmsg = PrivateMessage(self.cid, timestamp, sender_id, message)
            db.session.add(pmsg)
            db.session.commit()
        return timestamp

    def set_anonymous(self, sender_id, anonymous):
        self.is_anonymous[sender_id] = anonymous

    @staticmethod
    def get_chat(uid1, uid2):
        if ( uid1 < uid2 ): 
            chat_id  = "chat-" + uid1 + uid2
        else:
            chat_id  = "chat-" + uid2 + uid1
        chat_room = PrivateChatRoom.chats.get(chat_id, None)
        return chat_room if chat_room != None else PrivateChatRoom(uid1, uid2)
