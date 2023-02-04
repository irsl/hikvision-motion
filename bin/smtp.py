#!/usr/bin/env python3

# Inputs: 
# - volume /data where the files are stored
# - the environment variables processed below (IGNORE_ANNOTATIONS, UPLOAD_URL_PREFIX, NOTIFY_URL_TEMPLATE, CAM_1_Name, CAM_1_HiRes, CAM_1_LoRes)
# - GCP_PROJECT env variable
# - /athome/athome.txt to mute the motion detection process based on a condition like: if (ping -c 1 10.6.8.126 || ping -c 1 10.6.8.186) >/dev/null; then echo athome; else echo noonehome; fi > /athome/athome.txt
# - /etc/creds.json with a GCP service account key that has access to the Cloud Vision API and GCS
# - port 5514 where HikVision should push the SMTP notifications (without attachment)

from __future__ import print_function
from datetime import datetime
import asyncore
import smtpd
import glob
from collections import defaultdict
import os
import re
import subprocess
import time
import threading
import urllib.request
import urllib.parse
import traceback
import json
from collections import namedtuple

anno_str = os.getenv("IGNORE_ANNOTATIONS")
ANNOTATIONS_TO_IGNORE = [] if not anno_str else anno_str.split(",") # e.g. "Furniture,Table top,Table,Plant,Window blind,Fountain"
#print(ANNOTATIONS_TO_IGNORE)

class CamInfo: pass

CAMINFOS = {}
for key in os.environ:
    if not key.startswith("CAM_"): continue
    s = key.split("_")
    camno = s[1]
    skey = s[2]
    value = os.getenv(key)
    ci = CAMINFOS.get(camno)
    if not ci:
        ci = CamInfo()
        CAMINFOS[camno] = ci
    setattr(ci, skey, value)

UPLOAD_URL_PREFIX = os.getenv("UPLOAD_URL_PREFIX") # e.g. https://storage.googleapis.com/your-bucket/
NOTIFY_URL_TEMPLATE = os.getenv("NOTIFY_URL_TEMPLATE") # e.g. "https://www.notifymydevice.com/push?ApiKey=yourapikey&PushTitle=<PTITLE>&PushText=<PTEXT>"

def are_we_at_home():
    try:
       with open("/athome/athome.txt") as f:
          return "athome" in f.read()
    except:
       traceback.print_exc()
       return False

def get_interesting_annotations(annotations):
    re = []
    for r in annotations:
       if r not in ANNOTATIONS_TO_IGNORE:
          re.append(r)
    return re

def get_all_annotations(respstr):
    re = []
    try:
       resp = json.loads(respstr)
       for r in resp["responses"]:
          for l in r.get("localizedObjectAnnotations") or []:
              s = l["score"]
              if s < 0.75: continue

              re.append(l["name"])
    except:
       traceback.print_exc()
    return re

def cur_hour():
    return datetime.now().hour

def is_late_hour():
    h = cur_hour()
    #print("cur hour", h)
    return h >= 21 or h <= 7

def should_do_motion():
    athome = are_we_at_home()
    late_hour = is_late_hour()
    #print("athome:", athome, "late_hour", late_hour)
    return not athome or late_hour

def get_age_of_file_in_days(f):
    return (time.time() - os.path.getmtime(f))/86400

def fetch_url(url):
    try:
        urllib.request.urlopen(url)
    except:
        traceback.print_exc()

class DeleteOldFiles(threading.Thread):
    def run(self):
        while True:
            for file in list(glob.glob('/data/*.jpg*')):
                d = get_age_of_file_in_days(file)
                if d > 30:
                    os.unlink(file)
            time.sleep(86400)


class GrabPicThread(threading.Thread):
    def __init__(self, cinfo, picname):
        super().__init__()
        self.cinfo = cinfo
        self.picname = picname

    def run(self):
        my_env = os.environ.copy()
        my_env["DONT_ANNOTATE"] = "1"
        subprocess.run(['grab-snapshot-and-annotate.sh', self.cinfo.HiRes, self.picname], stdout=subprocess.PIPE,env=my_env)

class PicThread(threading.Thread):
    def __init__(self, cinfo, picname, vidurl):
        super().__init__()
        self.cinfo = cinfo
        self.picname = picname
        self.vidurl = vidurl

    def run(self):
        r = subprocess.run(['grab-snapshot-and-annotate.sh', self.cinfo.HiRes, self.picname], stdout=subprocess.PIPE)
        all_annotations = get_all_annotations(r.stdout)
        print("all annotations:", all_annotations)
        interesting = get_interesting_annotations(all_annotations)
        if len(interesting) <= 0:
            return
        interesting_str = ", ".join(interesting)
        ptitle = f"{self.cinfo.Name}"
        ptitle_ue = urllib.parse.quote(ptitle)
        ptext = f"{interesting_str}: {self.vidurl}"
        ptext_ue = urllib.parse.quote(ptext)
        url = NOTIFY_URL_TEMPLATE.replace("<PTITLE>", ptitle_ue).replace('<PTEXT>', ptext_ue)
        fetch_url(url)


class VidThread(threading.Thread):
    def __init__(self, cinfo, vidurl):
        super().__init__()
        self.cinfo = cinfo
        self.vidurl = vidurl

    def run(self):
        subprocess.run(['upload-short-video.sh',self.cinfo.LoRes, self.vidurl])

class EmlServer(smtpd.SMTPServer):
    counters = defaultdict(int)
    def process_message(self, peer, mailfrom, rcpttos, data, **kwargs):
        dstr = data.decode()
        m = re.search(r'Motion Detected On Channel D(\d+)', dstr)
        if not m:
           print("ERROR, unknown subject")
           print(data)
           return
        camno = m.group(1)
        self.counters[camno]+= 1
        c = self.counters[camno]
        now = datetime.now().strftime('%Y%m%d%H%M%S')
        bname = f'{now}-D{camno}-{c:08d}'
        picname = f'{bname}.jpg'
        cinfo = CAMINFOS[camno]
        print(picname)

        if not should_do_motion():
            print("Skipping motion detection, grabbing a single image")
            GrabPicThread(cinfo, picname).start()
            return

        vidname = f'{bname}.mp4'
        vidurl = UPLOAD_URL_PREFIX+vidname
        #print(f"PicThread: {hivid}, {picname}, {vidurl}")
        PicThread(cinfo, picname, vidurl).start()
        #print(f"VidThread: {lovid}, {vidurl}")
        VidThread(cinfo, vidurl).start()


def run():
    DeleteOldFiles().start()
    # start the smtp server on localhost:1025
    foo = EmlServer(('0.0.0.0', 5514), None)
    try:
        asyncore.loop()
    except KeyboardInterrupt:
        pass


if __name__ == '__main__':
    run()
