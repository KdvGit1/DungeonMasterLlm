import requests
import sys

url = "http://127.0.0.1:5000"
sess = requests.Session()

print("Logging in...")
r = sess.post(f"{url}/api/login", json={"username": "tester5", "password": "123", "action": "register"})
if r.status_code == 400:
    r = sess.post(f"{url}/api/login", json={"username": "tester5", "password": "123", "action": "login"})

print("Creating session...")
r = sess.post(f"{url}/api/sessions", json={"name": "test_sess5"})
print("Create session response:", r.text[:200])

print("Creating character...")
r = sess.post(f"{url}/api/characters/create", json={"name": "testhero", "race": "1", "class": "1", "background": "None"})
print("Create character response:", r.text[:200])

print("Sending Action...")
try:
    r = sess.post(f"{url}/api/game/action", json={"action": "I look around", "player_name": "testhero"})
    print(f"Status: {r.status_code}")
    if r.status_code != 200:
        with open("flask_error2.html", "w", encoding="utf-8") as f:
            f.write(r.text)
        print("Wrote error to flask_error2.html")
    else:
        print("Success!")
except Exception as e:
    print(f"Request failed: {e}")
