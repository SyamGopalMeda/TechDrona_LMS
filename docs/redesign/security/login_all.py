import json, sys
sys.path.insert(0, __file__.rsplit("\\",1)[0].rsplit("/",1)[0])
from td_client import login
for who in sys.argv[1:] or ["student","asha.student","ravi.student","trainer","evaluator","content","admin","admin2"]:
    try:
        c = login(who)
        me = c.get("me").json()
        print(who, me["user"].get("id"), "tier=", me["session"].get("session_tier"), "aal=", me["session"].get("aal"), "portals=", me.get("portals"))
    except Exception as e:
        print(who, "FAIL", e)
