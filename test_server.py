import subprocess, unittest, json, time, os
from multiprocessing import Process
from server.request_utils import send_request

SERVER_URL = "http://0.0.0.0:5000"

def do_start_server():
    subprocess.call(["foreman", "start"])

def start_server():
    p = Process(target=do_start_server)
    p.daemon = False
    p.start()
    time.sleep(3)

def do_stop_server():
    subprocess.call(["fuser", "-k", "5000/tcp"])

def stop_server():
    p = Process(target=do_stop_server)
    p.daemon = False
    p.start()
    time.sleep(1)

def prepare_and_send_request(method, endpoint, client, payload=None):
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json"
    }
    if ( method == "POST" ):
        if ( payload == None ):
            payload = {}
        payload["auth"] = os.environ.get("SERVER_PASS", os.urandom(24))
    response = send_request(method, SERVER_URL + endpoint,
        payload=payload, headers=headers, client=client)
    return response

def perform_basic_assertions(self, response):
    self.assertTrue(response['success'])
    self.assertEqual(response['code'], 200)
    return json.loads(response['content'])

class TestServerEndpoints(unittest.TestCase):

    def test_001_get_presence_unauthenticated(self):
        response = prepare_and_send_request('GET', '/presence',
            client='_1234567890')
        response = perform_basic_assertions(self, response)
        self.assertEqual(response['code'], "ok")
        self.assertEqual(response['user_id'], None)

    def test_002_authenticate(self):
        payload = {
            "first_name": "Username's First Name",
            "full_name": "Username's Full Name",
            "gender": "male",
            "nickname": "Username's Nick",
            "anonymous": "true",
            "location": "unknown"
        }
        response = prepare_and_send_request('POST', '/presence/_1234567890',
            client='_1234567890', payload=payload)
        response = perform_basic_assertions(self, response)
        self.assertEqual(response['code'], "ok")

    def test_003_get_presence_authenticated(self):
        response = prepare_and_send_request('GET', '/presence',
            client='_1234567890')
        response = perform_basic_assertions(self, response)
        self.assertEqual(response['code'], "ok")
        self.assertEqual(response['user_id'], "_1234567890")

    def test_004_authenticate_again(self):
        payload = {
            "first_name": "Username's First Name",
            "full_name": "Username's Full Name",
            "gender": "male",
            "nickname": "Username's Nick",
            "anonymous": "true",
            "location": "unknown"
        }
        response = prepare_and_send_request('POST', '/presence/_1234567890',
            client='_1234567890', payload=payload)
        response = perform_basic_assertions(self, response)
        self.assertEqual(response['code'], "ok")

    def test_005_get_presence_authenticated_again(self):
        response = prepare_and_send_request('GET', '/presence',
            client='_1234567890')
        response = perform_basic_assertions(self, response)
        self.assertEqual(response['code'], "ok")
        self.assertEqual(response['user_id'], "_1234567890")

    def test_006_authenticate_as_someone_else(self):
        payload = {
            "first_name": "Username's First Name",
            "full_name": "Username's Full Name",
            "gender": "male",
            "nickname": "Username's Nick",
            "anonymous": "true",
            "location": "unknown"
        }
        response = prepare_and_send_request('POST', '/presence/another_user',
            client='_1234567890', payload=payload)
        response = perform_basic_assertions(self, response)
        self.assertEqual(response['code'], "error")

    def test_007_exit(self):
        response = prepare_and_send_request('POST', '/exit',
            client='_1234567890')
        response = perform_basic_assertions(self, response)
        self.assertEqual(response['code'], "ok")

    def test_008_get_presence_after_exit(self):
        response = prepare_and_send_request('GET', '/presence',
            client='_1234567890')
        response = perform_basic_assertions(self, response)
        self.assertEqual(response['code'], "ok")
        self.assertEqual(response['user_id'], None)

    def test_009_exit_after_exit(self):
        response = prepare_and_send_request('POST', '/exit',
            client='_1234567890')
        response = perform_basic_assertions(self, response)
        self.assertEqual(response['code'], "error")

    def test_010_get_presence_after_failed_exit(self):
        response = prepare_and_send_request('GET', '/presence',
            client='_1234567890')
        response = perform_basic_assertions(self, response)
        self.assertEqual(response['code'], "ok")
        self.assertEqual(response['user_id'], None)

    def test_011_authenticate_again_after_exit(self):
        payload = {
            "first_name": "Username's First Name",
            "full_name": "Username's Full Name",
            "gender": "male",
            "nickname": "Username's Nick",
            "anonymous": "true",
            "location": "unknown"
        }
        response = prepare_and_send_request('POST', '/presence/_1234567890',
            client='_1234567890', payload=payload)
        response = perform_basic_assertions(self, response)
        self.assertEqual(response['code'], "ok")

    def test_012_get_presence_authenticated_once_again(self):
        response = prepare_and_send_request('GET', '/presence',
            client='_1234567890')
        response = perform_basic_assertions(self, response)
        self.assertEqual(response['code'], "ok")
        self.assertEqual(response['user_id'], "_1234567890")

    @classmethod
    def tearDownClass(cls):
        stop_server()

if __name__ == "__main__": 

    start_server()
    unittest.main(failfast=True)
