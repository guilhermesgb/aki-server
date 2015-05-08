from server import app, db
from server.models import StoredUser, UploadedImage
import os

port = int(os.environ.get("PORT", 5000))
db.create_all()

for user in StoredUser.query.all():
    user.active = False
    db.session.add(user)
db.session.commit()

for upload in UploadedImage.query.all():
    _file = open(os.path.join(app.config['UPLOADS_FOLDER'],
        upload.name), 'w')
    _file.write(upload.blob)
    _file.close()

app.run(host="0.0.0.0", port=port)
