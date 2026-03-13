import requests
import time
import uuid

BASE_URL = "http://localhost:5000"

def run_test():
    # 1. Register and login P1
    p1 = f"test_{uuid.uuid4().hex[:4]}"
    res = requests.post(f"{BASE_URL}/api/login", json={"username": p1, "password": "123", "action": "register"}).json()
    print("P1 Login:", res)
    
    # Register and login P2
    p2 = f"test_{uuid.uuid4().hex[:4]}"
    res = requests.post(f"{BASE_URL}/api/login", json={"username": p2, "password": "123", "action": "register"}).json()
    print("P2 Login:", res)

    # 2. Setup characters
    res1 = requests.post(f"{BASE_URL}/api/characters/create", json={"username": p1, "name": p1, "race": "human", "class": "fighter", "background": "Hero", "abilities": {"strength": 16, "dexterity": 14, "constitution": 14, "intelligence": 10, "wisdom": 10, "charisma": 10}}).json()
    print("P1 Char Create Response:", res1)
    char1 = res1.get("character")

    res2 = requests.post(f"{BASE_URL}/api/characters/create", json={"username": p2, "name": p2, "race": "elf", "class": "wizard", "background": "Hero", "abilities": {"strength": 10, "dexterity": 14, "constitution": 12, "intelligence": 16, "wisdom": 14, "charisma": 10}}).json()
    print("P2 Char Create Response:", res2)
    char2 = res2.get("character")

    # 3. Create room (P1 is Host)
    res = requests.post(f"{BASE_URL}/api/room/create", json={"username": p1, "session_name": "DebugRoom"}).json()
    room_code = res["room_code"]
    print("Room Created:", room_code)

    # 4. Join room
    requests.post(f"{BASE_URL}/api/room/join", json={"room_code": room_code, "username": p1, "character": char1})
    requests.post(f"{BASE_URL}/api/room/join", json={"room_code": room_code, "username": p2, "character": char2})
    print("Players Joined")

    # 5. Start Game
    res = requests.post(f"{BASE_URL}/api/room/start", json={"room_code": room_code, "username": p1, "scenario_path": ""}).json()
    print("Game Started")

    # 6. Submit Actions (triggering combat)
    print("Submitting Combat Actions...")
    requests.post(f"{BASE_URL}/api/game/submit_action", json={"room_code": room_code, "username": p1, "action": "I draw my sword and attack the guard in front of me!"})
    res = requests.post(f"{BASE_URL}/api/game/submit_action", json={"room_code": room_code, "username": p2, "action": "I cast a fireball at the guard!"}).json()
    
    print("Waiting for GM response...")
    time.sleep(5)
    
    # 7. Check Status
    for i in range(5):
        status = requests.get(f"{BASE_URL}/api/room/status?room_code={room_code}").json()
        if "round_result" in status:
            print("\n🚨 ROUND COMPLETE 🚨")
            print("Pending Encounter present?:", "pending_encounter" in status["round_result"])
            print("Current display data:", status["round_result"].get("pending_encounter"))
            break
        print(f"Status (processing: {status.get('round_processing')}): Waiting...")
        time.sleep(3)

if __name__ == "__main__":
    run_test()
