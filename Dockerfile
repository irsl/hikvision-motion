FROM alpine:latest
RUN apk add openssl curl jq bash ffmpeg python3 tzdata py3-numpy py3-opencv; cp /usr/share/zoneinfo/Europe/Budapest /etc/localtime
ADD bin /usr/local/bin/
ENTRYPOINT ["/usr/local/bin/smtp.py"]
