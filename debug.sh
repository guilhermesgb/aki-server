#!/bin/bash

DEBUG_PATH=/tmp/debug_lespi_landing_page

rm -rf $DEBUG_PATH
mkdir $DEBUG_PATH

echo "from flask import Flask, render_template
import os

server = Flask(__name__,
               static_folder='',
               static_url_path='',
               template_folder='')

@server.route('/')
def index():

    return render_template('index.html')

@server.route('/old')
def old_index():

    return render_template('index-old.html')

if __name__ == '__main__':

    port = int(os.environ.get('PORT', 5000))
    server.run(host='0.0.0.0', port=port, debug=True)" > $DEBUG_PATH/server.py

cp -R images/ $DEBUG_PATH/images

cp -R javascripts/ $DEBUG_PATH/javascripts

cp -R stylesheets/ $DEBUG_PATH/stylesheets

cp -R fonts/ $DEBUG_PATH/fonts

cp index.html $DEBUG_PATH/index.html

cp index-old.html $DEBUG_PATH/index-old.html

THIS_PATH=`pwd`
cd $DEBUG_PATH
python server.py ; cd $THIS_PATH
