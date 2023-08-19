#!/usr/bin/env python3

# Inputs:
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
import secrets
import urllib.request
import urllib.parse
import traceback
import json
from collections import namedtuple
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

DROP_SCORE = float(os.getenv("DROP_SCORE") or "0.45") # annotations that with score lower than this value are dropped entirely
MIN_SCORE = float(os.getenv("MIN_SCORE") or "0.7") # to send a notification about, unless it is among IMPORTANT_ANNOTATIONS
UPLOAD_URL_PREFIX = os.getenv("UPLOAD_URL_PREFIX") # e.g. https://storage.googleapis.com/your-bucket/
NOTIFY_URL_TEMPLATE = os.getenv("NOTIFY_URL_TEMPLATE") # e.g. "https://www.notifymydevice.com/push?ApiKey=yourapikey&PushTitle=<PTITLE>&PushText=<PTEXT>"

NIGHT_HOUR_BEGIN_AT = int(os.getenv("NIGHT_HOUR_BEGIN_AT") or "0")
NIGHT_HOUR_END_AT = int(os.getenv("NIGHT_HOUR_END_AT") or "0")

ignore_anno_str = os.getenv("IGNORE_ANNOTATIONS")
ANNOTATIONS_TO_IGNORE = [] if not ignore_anno_str else ignore_anno_str.split(",") # e.g. "Furniture,Table top,Table,Plant,Window blind,Fountain"
#print(ANNOTATIONS_TO_IGNORE)

prio_anno_str = os.getenv("IMPORTANT_ANNOTATIONS")
ANNOTATIONS_TO_PRIO = [] if not prio_anno_str else prio_anno_str.split(",") # e.g. "Furniture,Table top,Table,Plant,Window blind,Fountain"

INCLUDE_VIDURL_IN_NOTIFICATION = True
if os.getenv("DONT_INCLUDE_VIDURL_IN_NOTIFICATION"):
    INCLUDE_VIDURL_IN_NOTIFICATION = False


DATADIR = "/data"

class CamInfo: pass

TAGS = {}
PICTURES = {}
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

def are_we_at_home():
    try:
       with open("/athome/athome.txt") as f:
          return "athome" in f.read()
    except:
       traceback.print_exc()
       return False

def get_interesting_annotations(annotations):
    re = []
    # filtering by score and label importance
    for r in annotations:
       score = r["score"]
       name = r["name"]
       if name in ANNOTATIONS_TO_IGNORE:
          continue
       if score < DROP_SCORE:
          continue
       if score < MIN_SCORE and name not in ANNOTATIONS_TO_PRIO:
          continue
       re.append(name)
    return re

def get_all_annotations_vision_ai(resp):
    re = []
    for r in resp["responses"]:
       for l in r.get("localizedObjectAnnotations") or []:
          re.append({"name":l["name"], "score":l["score"]})
    return re

def get_all_annotations_sentisight(resp):
    re = []
    for r in resp:
       re.append({"name":r["label"], "score":r["score"]/100})
    return re

def get_all_annotations(respstr):
    re = []
    try:
       resp = json.loads(respstr)
       if type(resp) is list:
          re = get_all_annotations_sentisight(resp)
       elif resp.get("responses"):
          re = get_all_annotations_vision_ai(resp)
       else:
          raise Exception("Invalid structure")
    except:
       print("Error while reading annotations:", respstr)
       traceback.print_exc()
    return re

def cur_hour():
    return datetime.now().hour

def is_late_hour():
    if NIGHT_HOUR_BEGIN_AT == 0 and NIGHT_HOUR_END_AT == 0:
        # feature disabled, decision is made purely based on whether we are at home or not
        return False

    h = cur_hour()
    #print("cur hour", h)
    return h >= NIGHT_HOUR_BEGIN_AT or h <= NIGHT_HOUR_END_AT

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

def slurp(file):
    with open(file) as f:
        return f.read()

def add_pic(tag, picname):
    arr = PICTURES.get(tag)
    if not arr:
        arr = []
        PICTURES[tag] = arr
    PICTURES[tag].append(picname)

def reindex_files():
    PICTURES.clear()
    TAGS.clear()
    for file in list(glob.glob(DATADIR+'/*.jpg')):
        try:
            fn = os.path.basename(file)
            tags_path = file + ".tags"
            if os.path.exists(tags_path):
                resp_str = slurp(tags_path)
                all_annotations = get_all_annotations(resp_str)
                tags = get_interesting_annotations(all_annotations)
                TAGS[fn] = list(tags)
                if len(tags) == 0:
                    tags = ["no_objects"]
                else:
                    tags.append("objects")
                tags.append("w_annotation")
            else:
                tags = ["wo_annotation"]
            tags.append("all")
            for tag in tags:
                add_pic(tag, fn)
        except:
            pass
    #print(PICTURES)

class MyServer(BaseHTTPRequestHandler):
    def serve_motion(self):
        re =  "<table width='95%'>\n"
        for camno in CAMINFOS:
           cam = CAMINFOS[camno]
           hlsurl0 = None
           webstreams = ""
           for a in dir(cam):
               if not a.startswith("HlsUrl"): continue
               v = a[6:]
               url = getattr(cam, a)
               if v == "Preview":
                   hlsurl0 = url
                   continue
               webstreams += f"<a href='{url}'>{v}</a> "
           if not hlsurl0: continue
           re += f"<tr><td width='80%' align='right'><iframe src='{hlsurl0}' scrolling='no'></iframe></td><td width='20%' align='left'>D{camno}: {cam.Name}<br>{webstreams}</td></tr>\n"
        re += "</table>\n"
        return re

    def serve_still(self):
        p = urllib.parse.urlparse(self.path)
        qp = urllib.parse.parse_qs(p.query)
        selected_tag = (qp.get("tag") or [""])[0] or "all"
        re = "<div>\n"
        alltags = list(PICTURES.keys())
        alltags.sort()
        for tag in alltags:
            no = len(PICTURES[tag])
            tagq = tag.replace(" ", "+")
            re += f"  <a href='/motion/still.html?tag={tagq}'>{tag} ({no})</a>\n"
        re += "</div>\n"
        pix = list(PICTURES[selected_tag])
        pix.sort(reverse=True)
        re += "<div class='stills'>\n"
        for pic in pix:
            vid1 = ""
            vid2 = ""
            if pic in PICTURES["w_annotation"]:
                url = UPLOAD_URL_PREFIX+pic.replace(".jpg", ".mp4")
                vid1 = f"<a href='{url}' target='_blank'>"
                vid2 = "</a>"
            tags = ", ".join(TAGS.get(pic) or [])
            re += "<div class='still'>\n"
            re += f"<div>{vid1}<img src='/motion/{pic}' loading='lazy'>{vid2}</div>\n"
            re += f"<div>{pic}: {tags}</div>\n"
            re += "</div>"
        re += "</div>\n"

        return re

    def serve_pic(self):
        self.send_response(200)
        self.send_header("Content-type", "image/jpeg")
        self.end_headers()
        fname = os.path.basename(self.path)
        with open(DATADIR+"/"+fname, "rb") as f:
            data = f.read()
            self.wfile.write(data)

    def do_GET(self):
        if self.path == "/":
            self.send_response(307)
            self.send_header("Location", "/motion/")
            self.end_headers()
            return

        if self.path.endswith(".jpg") and "?" not in self.path and ".." not in self.path:
            self.serve_pic()
            return

        if self.path != "/motion/" and not self.path.startswith("/motion/still.html"):
            self.send_response(404)
            self.end_headers()
            return

        self.send_response(200)
        self.send_header("Content-type", "text/html")
        self.end_headers()

        # header
        data = "<!DOCTYPE html><html><head><meta name='viewport' content='width=device-width, initial-scale=1' /><title>Motion</title><style>div a { font-size: 16px; } .stills img { width: 100%; height: auto; } .still { margin-top: 10px; margin-right: 10px; } @media only screen and (min-width: 1081px) { .still {width: 45%; float: left;} }</style></head><body>\n"      
        data+= "<h1><a href='/motion/'>Live stream</a> | <a href='/motion/still.html'>Motions</a></h1>\n"

        if self.path == "/motion/":
            data += self.serve_motion()
        else:
            data += self.serve_still()

        # footer
        data += "</body></html>\n"
        self.wfile.write(data.encode())

class DeleteOldFiles(threading.Thread):
    def run(self):
        while True:
            for file in list(glob.glob(DATADIR+'/*.jpg*')):
                d = get_age_of_file_in_days(file)
                if d > 30:
                    os.unlink(file)
            reindex_files()
            try:
                time.sleep(86400)
            except:
                return

class WebThread(threading.Thread):
    def run(self):
        hostName = "0.0.0.0"
        serverPort = 8080
        webServer = ThreadingHTTPServer((hostName, serverPort), MyServer)
        print("Server started http://%s:%s" % (hostName, serverPort))
        try:
            webServer.serve_forever()
        except KeyboardInterrupt:
            pass

        webServer.server_close()
        print("Server stopped.")

class EmailThread(threading.Thread):
    def run(self):
        # start the smtp server on localhost:1025
        foo = EmlServer(('0.0.0.0', 5514), None)
        try:
            asyncore.loop()
        except KeyboardInterrupt:
            pass

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
        TAGS[self.picname] = interesting
        add_pic("w_annotation", self.picname)
        if len(interesting) <= 0:
            add_pic("no_objects", self.picname)
            return
        add_pic("objects", self.picname)
        for tag in interesting:
            add_pic(tag, self.picname)
        interesting_str = ", ".join(interesting)
        ptitle = f"{self.cinfo.Name}"
        ptitle_ue = urllib.parse.quote(ptitle)
        ptext = f"{interesting_str}"
        if INCLUDE_VIDURL_IN_NOTIFICATION:
            ptext += f": {self.vidurl}"
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
        now = datetime.now().strftime('%Y%m%d-%H%M%S')
        secret = secrets.token_hex(8)
        bname = f'{now}-D{camno}-{c:08d}-{secret}'
        picname = f'{bname}.jpg'
        cinfo = CAMINFOS[camno]
        print(picname)
        add_pic("all", picname)

        if not should_do_motion():
            print("Skipping motion detection, grabbing a single image")
            GrabPicThread(cinfo, picname).start()
            add_pic('wo_annotation', picname)
            return

        vidname = f'{bname}.mp4'
        vidurl = UPLOAD_URL_PREFIX+vidname
        #print(f"PicThread: {hivid}, {picname}, {vidurl}")
        PicThread(cinfo, picname, vidurl).start()
        #print(f"VidThread: {lovid}, {vidurl}")
        VidThread(cinfo, vidurl).start()


def run():
    DeleteOldFiles().start()
    WebThread().start()
    EmailThread().start()

if __name__ == '__main__':
    run()
