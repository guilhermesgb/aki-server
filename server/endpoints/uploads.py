from .. import app, db
from ..models import UploadedImage
from flask import make_response, request, send_from_directory
from flask.ext.login import login_required, current_user
from werkzeug import secure_filename
import os, json


@app.route('/upload', methods=['POST'])
@login_required
def upload_file():

    _file = request.files['filename']
    if ( _file and allowed_file(_file.filename) ):
        filename = secure_filename(_file.filename)

        if ( current_user.get_id() in filename ):
            path = os.path.join(app.config['UPLOADS_FOLDER'], filename)
            _file.save(path)
            _file = open(path, 'r')
            _stored = UploadedImage(filename, _file.read())
            _file.close()
            db.session.add(_stored)
            db.session.commit()
            response = make_response(json.dumps({'server':filename + ' uploaded!', 'code':'ok'}), 200)
        else:
            response = make_response(json.dumps({'server':'you don\'t have permission to upload this file!', 'code':'error'}), 200)
    else:
        response = make_response(json.dumps({'server':filename + ' could not be uploaded!', 'code':'error'}), 200)
    response.headers["Content-Type"] = "application/json"
    return response

@app.route('/upload/<filename>', methods=['GET', 'HEAD'])
@login_required
def serve_uploaded_file(filename):
    return send_from_directory(app.config['UPLOADS_FOLDER'], filename)

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1] in ['png', 'jpg', 'jpeg']
