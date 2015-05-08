from server import db

class StoredUser(db.Model):

    __tablename__ = 'person'
    id = db.Column(db.Integer, primary_key=True)
    uid = db.Column(db.String(20), unique=True)
    nickname = db.Column(db.String(13))
    gender = db.Column(db.String(50))
    first_name = db.Column(db.String(50))
    full_name = db.Column(db.String(50))
    active = db.Column(db.Boolean)

    def __init__(self, user_id, nickname, gender, \
      first_name, full_name, active=False):
        self.uid = user_id
        self.nickname = nickname
        self.gender = gender
        self.first_name = first_name
        self.full_name = full_name
        self.active = active

    def __repr__(self):
        return "<Username {}>".format(self.uid)

class PrivateMessage(db.Model):

    __tablename__ = "private_message"
    id = db.Column(db.Integer, primary_key=True)
    cid = db.Column(db.String(50))
    timestamp = db.Column(db.String(50))
    sender_id = db.Column(db.String(50))
    message = db.Column(db.Text)

    def __init__(self, cid, timestamp, sender_id, message):
        self.cid = cid
        self.timestamp = timestamp
        self.sender_id = sender_id
        self.message = message

    def __repr__(self):
        return "PrivateMessage from {}".format(self.sender_id)

class MutualInterest(db.Model):

    __tablename__ = 'mutual'
    id = db.Column(db.Integer, primary_key=True)
    uid1 = db.Column(db.String(50))
    uid2 = db.Column(db.String(50))

    def __init__(self, uid1, uid2):
        self.uid1 = uid1
        self.uid2 = uid2

    def __repr__(self):
        return "<Mutual {} & {}>".format(self.uid1, self.uid2)

class UploadedImage(db.Model):

    __tablename__ = "uploaded_image"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50))
    blob = db.Column(db.LargeBinary())

    def __init__(self, name, blob):
        self.name = name
        self.blob = blob

    def __repr__(self):
        return "UploadedImage {}".format(self.name)
